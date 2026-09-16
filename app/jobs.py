"""Job store persisted to Zerobox SQLite (shared across replicas and survives
sleeps/restarts) + background worker for a single Excel-to-ZIP run."""
from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
import uuid
import zipfile
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, insert, update
from sqlalchemy.schema import CreateTable
from sqlmodel import Field, SQLModel, select

from .excel_parser import Row
from .imaging import MAX_WORKERS, NameRegistry, build_session, download_and_process
from src.zerobox.sqlite import SQLITE_DIALECT, ZeroboxSQLite, _compile

JOBS_ROOT = Path(__file__).resolve().parent.parent / ".jobs"
JOBS_ROOT.mkdir(parents=True, exist_ok=True)
JOB_TTL_SECONDS = 2 * 60 * 60  # 2 hours
PROGRESS_FLUSH_SECONDS = 1.0


class JobRecord(SQLModel, table=True):
    __tablename__ = "job"
    id: str = Field(primary_key=True)
    status: str = "pending"
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    cancel_requested: bool = False
    error_message: Optional[str] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


class JobFailureRecord(SQLModel, table=True):
    __tablename__ = "job_failure"
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str
    sku: str
    url: str
    reason: str


class _LocalDevSQLite:
    """Local-only stand-in for ZeroboxSQLite, used when ZEROBOX_SQLITE_URL isn't
    set (plain `uvicorn` runs outside the Zerobox runtime). Never used in
    production - the deployed app always has the real bridge available."""

    def __init__(self) -> None:
        path = JOBS_ROOT / "local-dev.sqlite3"
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()

    def run(self, statement) -> None:
        sql, params = _compile(statement)
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def fetch_all(self, statement) -> list[list[object]]:
        sql, params = _compile(statement)
        with self._lock:
            cursor = self._conn.execute(sql, params)
            return [list(row) for row in cursor.fetchall()]

    def fetch_models(self, statement, model):
        expected_keys = [column.key for column in model.__table__.columns]
        return [
            model.model_validate(dict(zip(expected_keys, row))) for row in self.fetch_all(statement)
        ]

    def fetch_model(self, statement, model):
        models = self.fetch_models(statement.limit(2), model)
        if len(models) > 1:
            raise TypeError("fetch_model requires a query bounded to one row")
        return models[0] if models else None

    def create_table(self, model) -> None:
        ddl = str(CreateTable(model.__table__, if_not_exists=True).compile(dialect=SQLITE_DIALECT))
        with self._lock:
            self._conn.executescript(ddl)


_db = None


def _get_db():
    global _db
    if _db is None:
        _db = ZeroboxSQLite() if os.environ.get("ZEROBOX_SQLITE_URL") else _LocalDevSQLite()
    return _db


def init_db() -> None:
    db = _get_db()
    db.create_table(JobRecord)
    db.create_table(JobFailureRecord)


class Job:
    """Read-only view over a JobRecord row, plus the local zip path (if any)."""

    def __init__(
        self,
        id: str,
        dir: Path,
        total: int,
        status: str = "pending",
        processed: int = 0,
        succeeded: int = 0,
        failed: int = 0,
        error_message: Optional[str] = None,
        created_at: float = 0.0,
        started_at: Optional[float] = None,
        finished_at: Optional[float] = None,
    ) -> None:
        self.id = id
        self.dir = dir
        self.total = total
        self.status = status
        self.processed = processed
        self.succeeded = succeeded
        self.failed = failed
        self.error_message = error_message
        self.created_at = created_at
        self.started_at = started_at
        self.finished_at = finished_at

    @property
    def zip_path(self) -> Optional[Path]:
        path = self.dir / "output.zip"
        return path if path.exists() else None

    def to_public_dict(self) -> dict:
        elapsed_seconds = None
        eta_seconds = None
        if self.started_at is not None:
            end = self.finished_at if self.finished_at is not None else time.time()
            elapsed_seconds = end - self.started_at
            if self.finished_at is None and 0 < self.processed < self.total:
                rate = elapsed_seconds / self.processed
                eta_seconds = rate * (self.total - self.processed)

        failure_rows = _get_db().fetch_all(
            select(JobFailureRecord.sku, JobFailureRecord.url, JobFailureRecord.reason)
            .where(JobFailureRecord.job_id == self.id)
            .limit(200)
        )

        return {
            "id": self.id,
            "status": self.status,
            "total": self.total,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "failures": [
                {"sku": sku, "url": url, "reason": reason} for sku, url, reason in failure_rows
            ],
            "error_message": self.error_message,
            "download_ready": self.status in ("done", "cancelled"),
            "cancellable": self.status == "running",
            "elapsed_seconds": elapsed_seconds,
            "eta_seconds": eta_seconds,
        }


def _cleanup_stale_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    for job_dir in JOBS_ROOT.iterdir():
        if job_dir.is_dir() and job_dir.stat().st_mtime < cutoff:
            shutil.rmtree(job_dir, ignore_errors=True)
    db = _get_db()
    db.run(delete(JobRecord).where(JobRecord.created_at < cutoff))
    db.run(delete(JobFailureRecord).where(JobFailureRecord.job_id.not_in(select(JobRecord.id))))


def create_job(rows: list[Row]) -> Job:
    _cleanup_stale_jobs()
    job_id = uuid.uuid4().hex
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    _get_db().run(
        insert(JobRecord).values(
            id=job_id,
            status="pending",
            total=len(rows),
            processed=0,
            succeeded=0,
            failed=0,
            cancel_requested=False,
            error_message=None,
            created_at=now,
            started_at=None,
            finished_at=None,
        )
    )
    return Job(id=job_id, dir=job_dir, total=len(rows), status="pending", created_at=now)


def get_job(job_id: str) -> Optional[Job]:
    record = _get_db().fetch_model(select(JobRecord).where(JobRecord.id == job_id), JobRecord)
    if record is None:
        return None
    return Job(
        id=record.id,
        dir=JOBS_ROOT / record.id,
        total=record.total,
        status=record.status,
        processed=record.processed,
        succeeded=record.succeeded,
        failed=record.failed,
        error_message=record.error_message,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def cancel_job(job: Job) -> bool:
    if job.status != "running":
        return False
    _get_db().run(
        update(JobRecord)
        .where(JobRecord.id == job.id, JobRecord.status == "running")
        .values(cancel_requested=True)
    )
    return True


def _is_cancel_requested(job_id: str) -> bool:
    record = _get_db().fetch_model(select(JobRecord).where(JobRecord.id == job_id), JobRecord)
    return bool(record and record.cancel_requested)


def start_job(
    job: Job,
    rows: list[Row],
    prefix: str,
    target_width: int,
    target_height: int,
    padding_factor: float,
) -> None:
    thread = threading.Thread(
        target=_run_job,
        args=(job.id, job.dir, rows, prefix, target_width, target_height, padding_factor),
        daemon=True,
    )
    thread.start()


def _run_job(
    job_id: str,
    job_dir: Path,
    rows: list[Row],
    prefix: str,
    target_width: int,
    target_height: int,
    padding_factor: float,
) -> None:
    output_dir = job_dir / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    db = _get_db()

    db.run(update(JobRecord).where(JobRecord.id == job_id).values(status="running", started_at=time.time()))

    try:
        session = build_session()
        names = NameRegistry()
        executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

        futures = {
            executor.submit(
                download_and_process,
                session,
                row,
                output_dir,
                prefix,
                target_width,
                target_height,
                padding_factor,
                names,
            ): row
            for row in rows
        }

        pending_processed = 0
        pending_succeeded = 0
        pending_failed = 0
        last_flush = time.time()
        cancelled = False

        def flush_progress() -> None:
            nonlocal pending_processed, pending_succeeded, pending_failed
            if pending_processed:
                db.run(
                    update(JobRecord)
                    .where(JobRecord.id == job_id)
                    .values(
                        processed=JobRecord.processed + pending_processed,
                        succeeded=JobRecord.succeeded + pending_succeeded,
                        failed=JobRecord.failed + pending_failed,
                    )
                )
                pending_processed = pending_succeeded = pending_failed = 0

        for future in as_completed(futures):
            try:
                result = future.result()
            except CancelledError:
                continue

            pending_processed += 1
            if result.success:
                pending_succeeded += 1
            else:
                pending_failed += 1
                db.run(
                    insert(JobFailureRecord).values(
                        job_id=job_id, sku=result.row.sku, url=result.row.url, reason=result.reason
                    )
                )

            now = time.time()
            if now - last_flush > PROGRESS_FLUSH_SECONDS:
                flush_progress()
                cancelled = _is_cancel_requested(job_id)
                last_flush = now

            if cancelled:
                # Cancel queued work and stop draining as_completed right away: continuing to
                # iterate it after cancel_futures=True can deadlock. Don't wait for the handful
                # of already-running downloads either - "stop" should feel immediate, not
                # blocked on a slow network timeout. Their results are simply dropped; the
                # executor's own threads finish up and exit on their own in the background.
                executor.shutdown(wait=False, cancel_futures=True)
                break
        else:
            executor.shutdown(wait=True)

        flush_progress()

        zip_path = job_dir / "output.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(output_dir.iterdir()):
                archive.write(file_path, arcname=file_path.name)

        db.run(
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .values(status="cancelled" if cancelled else "done", finished_at=time.time())
        )
    except Exception as error:  # noqa: BLE001 - reported to the UI instead of crashing the thread
        db.run(
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .values(status="error", error_message=str(error), finished_at=time.time())
        )
