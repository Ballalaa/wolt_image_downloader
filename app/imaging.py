"""Image download + processing pipeline.

Ports the team's existing scripts into a single per-row function the job
runner can call concurrently: the download/retry setup from ImgDownloader.py,
the 406-avoidance headers from ImgDownloaderSizer.py, and the background-strip
/ smart-scale / pad-to-canvas logic from resizer.py.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageChops
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .excel_parser import Row

MAX_WORKERS = 20
REQUEST_TIMEOUT = 20

# Browser-like headers avoid the HTTP 406 some CDNs return to bare `requests` calls.
# Accept deliberately excludes avif/webp: several CDNs (e.g. Wolt's own menu-image CDN)
# content-negotiate on this header and will serve AVIF, which stock Pillow can't decode.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    ),
    "Accept": "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}

_UNSAFE_CHARS = re.compile(r'[\\/*?:"<>|]+')


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries, pool_maxsize=MAX_WORKERS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class NameRegistry:
    """Thread-safe de-duper: two rows sharing a SKU get `_2`, `_3`, ... suffixes
    instead of silently overwriting each other's output file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def reserve(self, base_name: str) -> str:
        with self._lock:
            count = self._counts.get(base_name, 0) + 1
            self._counts[base_name] = count
        return base_name if count == 1 else f"{base_name}_{count}"


def sanitize_component(value: str) -> str:
    return _UNSAFE_CHARS.sub("_", value).strip()


def process_image(
    content: bytes, target_width: int, target_height: int, padding_factor: float
) -> bytes:
    img = Image.open(BytesIO(content))

    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    else:
        img = img.convert("RGB")

    # Sample the corner pixel and crop out a matching solid-color background,
    # ignoring minor JPEG-compression noise.
    bg_color = img.getpixel((0, 0))
    bg = Image.new("RGB", img.size, bg_color)
    diff = ImageChops.difference(img, bg)
    diff = diff.point(lambda x: 0 if x < 15 else 255)
    bbox = diff.getbbox()

    if bbox and (bbox[2] - bbox[0] > 5) and (bbox[3] - bbox[1] > 5):
        img = img.crop(bbox)

    width_ratio = (target_width * padding_factor) / img.width
    height_ratio = (target_height * padding_factor) / img.height
    scale_factor = min(width_ratio, height_ratio)

    new_width = max(1, round(img.width * scale_factor))
    new_height = max(1, round(img.height * scale_factor))
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (target_width, target_height), (255, 255, 255))
    x = (target_width - new_width) // 2
    y = (target_height - new_height) // 2
    canvas.paste(img, (x, y))

    buffer = BytesIO()
    canvas.save(buffer, "JPEG", quality=100, subsampling=0, optimize=True)
    return buffer.getvalue()


@dataclass
class RowResult:
    row: Row
    success: bool
    filename: Optional[str] = None
    reason: Optional[str] = None


def download_and_process(
    session: requests.Session,
    row: Row,
    output_dir: Path,
    prefix: str,
    target_width: int,
    target_height: int,
    padding_factor: float,
    names: NameRegistry,
) -> RowResult:
    if not row.url.startswith(("http://", "https://")):
        return RowResult(row, False, reason=f"Invalid URL: {row.url}")

    try:
        response = session.get(row.url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        return RowResult(row, False, reason=f"Download failed: {error}")

    try:
        processed = process_image(response.content, target_width, target_height, padding_factor)
    except Exception as error:  # noqa: BLE001 - any decode/processing error becomes a row failure
        return RowResult(row, False, reason=f"Image processing failed: {error}")

    base_name = sanitize_component(f"{prefix}{row.sku}") or f"row_{row.index}"
    filename = f"{names.reserve(base_name)}.jpg"
    (output_dir / filename).write_bytes(processed)
    return RowResult(row, True, filename=filename)
