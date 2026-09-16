"""FastAPI app: Excel upload -> background download/resize job -> ZIP download."""
from __future__ import annotations

import base64
from pathlib import Path

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .excel_parser import parse_workbook
from .imaging import REQUEST_TIMEOUT, build_session, process_image
from .jobs import cancel_job, create_job, get_job, init_db, start_job

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

DEFAULT_WIDTH = 2880
DEFAULT_HEIGHT = 1620
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

app = FastAPI(title="Wolt Image Tool")


@app.on_event("startup")
async def on_startup() -> None:
    init_db()


@app.get("/health/readiness")
async def readiness() -> dict:
    return {"status": "ok"}


async def _read_excel_upload(file: UploadFile) -> bytes:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Please upload an .xlsx or .xls file.")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File is too large (limit 20 MB).")
    return content


def _resolve_dimensions(size_mode: str, width: int, height: int) -> tuple[int, int]:
    if size_mode == "custom":
        if width < 100 or height < 100 or width > 8000 or height > 8000:
            raise HTTPException(400, "Custom dimensions must be between 100 and 8000 pixels.")
        return width, height
    return DEFAULT_WIDTH, DEFAULT_HEIGHT


@app.post("/api/preview")
async def preview(file: UploadFile = File(...)) -> dict:
    content = await _read_excel_upload(file)
    try:
        rows = parse_workbook(content)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    all_rows = [{"sku": row.sku, "url": row.url} for row in rows]
    return {"row_count": len(rows), "rows": all_rows}


@app.post("/api/jobs")
async def create_job_endpoint(
    file: UploadFile = File(...),
    prefix_enabled: bool = Form(False),
    prefix: str = Form(""),
    size_mode: str = Form("default"),
    width: int = Form(DEFAULT_WIDTH),
    height: int = Form(DEFAULT_HEIGHT),
    padding: float = Form(50.0),
) -> dict:
    content = await _read_excel_upload(file)
    try:
        rows = parse_workbook(content)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    target_width, target_height = _resolve_dimensions(size_mode, width, height)
    padding_factor = max(0.1, min(1.0, padding / 100.0))
    resolved_prefix = prefix.strip() if prefix_enabled else ""

    job = create_job(rows)
    start_job(job, rows, resolved_prefix, target_width, target_height, padding_factor)
    return {"job_id": job.id}


@app.post("/api/preview-image")
async def preview_image(
    file: UploadFile = File(...),
    row_index: int = Form(0),
    size_mode: str = Form("default"),
    width: int = Form(DEFAULT_WIDTH),
    height: int = Form(DEFAULT_HEIGHT),
    padding: float = Form(50.0),
) -> dict:
    content = await _read_excel_upload(file)
    try:
        rows = parse_workbook(content)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    if not 0 <= row_index < len(rows):
        raise HTTPException(400, "That row is out of range.")

    target_width, target_height = _resolve_dimensions(size_mode, width, height)
    padding_factor = max(0.1, min(1.0, padding / 100.0))
    row = rows[row_index]

    session = build_session()
    try:
        response = session.get(row.url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        raise HTTPException(502, f"Could not download the sample image: {error}") from error

    try:
        processed = process_image(response.content, target_width, target_height, padding_factor)
    except Exception as error:  # noqa: BLE001 - surfaced to the UI as a preview error
        raise HTTPException(502, f"Could not process the sample image: {error}") from error

    return {
        "sku": row.sku,
        "url": row.url,
        "processed_base64": base64.b64encode(processed).decode("ascii"),
    }


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job.to_public_dict()


@app.post("/api/jobs/{job_id}/cancel")
async def job_cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    if not cancel_job(job):
        raise HTTPException(409, "Job is not running.")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/download")
async def job_download(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    if job.status not in ("done", "cancelled"):
        raise HTTPException(409, "Job is not finished yet.")
    if job.zip_path is None:
        raise HTTPException(
            409,
            "This job finished on a different server instance and its file isn't available "
            "here. Please try downloading again.",
        )
    return FileResponse(job.zip_path, filename="wolt-images.zip", media_type="application/zip")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
