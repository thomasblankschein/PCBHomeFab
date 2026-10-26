"""FastAPI application: anonymous jobs with upload, queue, status and download.

There are no accounts. Creating a job returns a random id; the job link ``/jobs/<id>`` is the only credential.
"""

from __future__ import annotations

import hashlib
import html
import io
import logging
import re
import secrets
import threading
import time
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from ..board import MAX_UNPACKED_BYTES, MAX_ZIP_FILES
from ..profiles import MILLS, PRINTERS
from ..tools import load_tools
from .config import Settings
from .store import DONE, FAILED, QUEUED, RUNNING, JobRecord, JobStore
from .worker import worker_loop

log = logging.getLogger("pcbhomefab.api")
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{20,32}$")
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")
INLINE_TYPES = {"image/png", "image/svg+xml", "text/plain; charset=utf-8"}


def _client_hash(request: Request, settings: Settings) -> str:
    address = request.client.host if request.client else "unknown"
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        address = forwarded.split(",")[0].strip() or address
    return hashlib.sha256(f"{settings.ip_salt}:{address}".encode()).hexdigest()[:32]


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    data = bytearray()
    while chunk := await upload.read(64 * 1024):
        data += chunk
        if len(data) > limit:
            raise HTTPException(413, f"A file is larger than {limit // (1024 * 1024)} MB.")
    return bytes(data)


def _check_zip(name: str, data: bytes) -> None:
    """Cheap checks only; the files are read for real in the worker."""
    try:
        entries = zipfile.ZipFile(io.BytesIO(data)).infolist()
    except zipfile.BadZipFile as exc:
        raise HTTPException(422, f"'{name}' is not a valid ZIP file.") from exc
    if len(entries) > MAX_ZIP_FILES or sum(e.file_size for e in entries) > MAX_UNPACKED_BYTES:
        raise HTTPException(422, f"'{name}' contains too many or too large files.")


def _job_links(record: JobRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "status": record.status,
        "page": f"/jobs/{record.id}",
        "api": f"/api/jobs/{record.id}",
    }


def _job_json(record: JobRecord) -> dict[str, Any]:
    return {
        **_job_links(record),
        "created": record.created,
        "expires": record.expires,
        "error": record.error,
        "params": record.params,
        "files": [{**f, "url": f"/api/jobs/{record.id}/files/{f['name']}"} for f in record.files],
    }


def _page(title: str, body: str, refresh: bool = False) -> HTMLResponse:
    meta = '<meta http-equiv="refresh" content="3">' if refresh else ""
    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{meta}<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;"
        "line-height:1.5}code{background:#eee;padding:0 .3em}.error{color:#b00020}</style></head>"
        f"<body>{body}</body></html>"
    )
    return HTMLResponse(document)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = JobStore(settings)
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        threads = [
            threading.Thread(target=worker_loop, args=(store, settings, stop), name=f"worker-{i}", daemon=True)
            for i in range(settings.embedded_workers)
        ]
        for thread in threads:
            thread.start()
        yield
        stop.set()
        for thread in threads:
            thread.join(timeout=5)

    app = FastAPI(title="PCBHomeFab", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/tools")
    async def tool_library() -> dict[str, Any]:
        return load_tools().to_dict()

    @app.get("/api/profiles")
    async def profiles() -> dict[str, Any]:
        return {
            "printers": {
                key: {
                    "name": p.name,
                    "resolution": [p.resolution_x, p.resolution_y],
                    "frame_left_mm": p.frame_left_mm,
                    "frame_bottom_mm": p.frame_bottom_mm,
                    "mirror_x": p.mirror_x,
                    "border_mm": p.border_mm,
                    "default_exposure_s": p.default_exposure_s,
                }
                for key, p in PRINTERS.items()
            },
            "mills": {
                key: {
                    "name": m.name,
                    "max_spindle_rpm": m.max_spindle_rpm,
                    "outline_endmill_mm": m.outline_endmill_mm,
                    "flip": m.flip,
                }
                for key, m in MILLS.items()
            },
            "limits": {
                "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
                "max_files": settings.max_files,
                "max_boards": settings.max_boards,
                "job_ttl_hours": settings.job_ttl_s / 3600,
            },
        }

    async def create_job(
        request: Request,
        boards: list[UploadFile],
        counts: list[int] | None,
        options: dict[str, Any],
    ) -> JobRecord:
        client = _client_hash(request, settings)
        if store.recent_count(client) >= settings.rate_limit_per_hour:
            raise HTTPException(429, "Too many jobs. Try again later.", headers={"Retry-After": "3600"})
        if store.queued_count() >= settings.max_queued:
            raise HTTPException(503, "The queue is full. Try again later.", headers={"Retry-After": "300"})
        if not boards or len(boards) > settings.max_files:
            raise HTTPException(422, f"Send between 1 and {settings.max_files} Gerber ZIP files.")
        counts = counts or [1] * len(boards)
        if len(counts) != len(boards) or any(c < 1 for c in counts):
            raise HTTPException(422, "Give one count (at least 1) for every file.")
        if sum(counts) > settings.max_boards:
            raise HTTPException(422, f"At most {settings.max_boards} boards fit in one job.")

        uploads: list[tuple[str, bytes]] = []
        for upload in boards:
            data = await _read_limited(upload, settings.max_upload_bytes)
            label = upload.filename or "board.zip"
            _check_zip(label, data)
            uploads.append((SAFE_NAME.sub("_", Path(label).stem)[:40] or "board", data))

        job_id = secrets.token_urlsafe(16)
        job_dir = store.job_dir(job_id)
        (job_dir / "input").mkdir(parents=True)
        entries = []
        for index, ((name, data), count) in enumerate(zip(uploads, counts, strict=True)):
            filename = f"board{index}.zip"
            (job_dir / "input" / filename).write_bytes(data)
            entries.append({"file": filename, "name": name, "count": count})
        params = {**options, "boards": entries}
        return store.create(job_id, params, client)

    @app.post("/api/jobs", status_code=201)
    async def post_job(
        request: Request,
        boards: Annotated[list[UploadFile], File(description="Gerber ZIP files, one per board design")],
        counts: Annotated[list[int] | None, Form(description="Copies per file, same order")] = None,
        printer: Annotated[Literal["photon-m3"], Form()] = "photon-m3",
        mill: Annotated[Literal["3018pro"], Form()] = "3018pro",
        exposure: Annotated[bool, Form()] = True,
        mill_gcode: Annotated[bool, Form()] = True,
        exposure_s: Annotated[float, Form(ge=1, le=3600)] = 120.0,
        holes: Annotated[Literal["full", "center", "none"], Form()] = "full",
        gap_mm: Annotated[float, Form(ge=0.5, le=20)] = 3.0,
        margin_mm: Annotated[float, Form(ge=0, le=20)] = 3.0,
        flip: Annotated[Literal["x", "y", "none"], Form()] = "x",
        thickness_mm: Annotated[float, Form(ge=0.4, le=3.2)] = 1.5,
        tabs: Annotated[bool, Form()] = True,
        frame_left_mm: Annotated[float, Form(ge=0, le=20)] = PRINTERS["photon-m3"].frame_left_mm,
        frame_bottom_mm: Annotated[float, Form(ge=0, le=20)] = PRINTERS["photon-m3"].frame_bottom_mm,
        mirror_x: Annotated[bool, Form()] = True,
    ) -> JSONResponse:
        options = {
            "printer": printer,
            "mill": mill,
            "exposure": exposure,
            "mill_gcode": mill_gcode,
            "exposure_s": exposure_s,
            "holes": holes,
            "gap_mm": gap_mm,
            "margin_mm": margin_mm,
            "flip": flip,
            "thickness_mm": thickness_mm,
            "tabs": tabs,
            "frame_left_mm": frame_left_mm,
            "frame_bottom_mm": frame_bottom_mm,
            "mirror_x": mirror_x,
        }
        if not exposure and not mill_gcode:
            raise HTTPException(422, "Select at least one output (exposure or mill_gcode).")
        record = await create_job(request, boards, counts, options)
        return JSONResponse(_job_links(record), status_code=201, headers={"Location": f"/api/jobs/{record.id}"})

    def _find(job_id: str) -> JobRecord:
        record = store.get(job_id) if JOB_ID.match(job_id) else None
        if record is None:
            raise HTTPException(404, "Job not found or expired.")
        return record

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        return _job_json(_find(job_id))

    @app.get("/api/jobs/{job_id}/files/{name:path}")
    async def get_file(job_id: str, name: str) -> FileResponse:
        record = _find(job_id)
        info = next((f for f in record.files if f["name"] == name), None)
        if record.status != DONE or info is None:
            raise HTTPException(404, "File not found.")
        path = store.job_dir(job_id) / "output" / info["name"]
        disposition = "inline" if info["content_type"] in INLINE_TYPES else "attachment"
        return FileResponse(
            path,
            media_type=info["content_type"],
            filename=Path(info["name"]).name,
            content_disposition_type=disposition,
            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'"},
        )

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_page(job_id: str) -> HTMLResponse:
        record = _find(job_id)
        title = f"Job {record.id}"
        if record.status in (QUEUED, RUNNING):
            body = f"<h1>{html.escape(title)}</h1><p>Status: <b>{record.status}</b>. This page refreshes itself.</p>"
            return _page(title, body, refresh=True)
        if record.status == FAILED:
            body = (
                f'<h1>{html.escape(title)}</h1><p class="error">The job failed: {html.escape(record.error or "")}</p>'
            )
            return _page(title, body)
        items = "".join(
            f'<li><a href="/api/jobs/{record.id}/files/{html.escape(f["name"])}">{html.escape(f["name"])}</a> '
            f"({f['size'] // 1024 + 1} KB)</li>"
            for f in record.files
        )
        preview = ""
        if any(f["name"] == "mask_preview.png" for f in record.files):
            preview = (
                f'<p><img src="/api/jobs/{record.id}/files/mask_preview.png" alt="mask" style="max-width:100%"></p>'
            )
        days = max(1, round((record.expires - time.time()) / 86400))
        body = (
            f"<h1>{html.escape(title)}</h1><p>Done. Files are kept for about {days} more day(s). "
            f"Keep this link, it is the only way to get them back.</p>{preview}<ul>{items}</ul>"
        )
        return _page(title, body)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        body = (
            "<h1>PCBHomeFab</h1><p>Gerber ZIP in, exposure file (<code>.pm3</code>) and drill/mill G-code out.</p>"
            '<form action="/jobs" method="post" enctype="multipart/form-data">'
            '<p><label>Gerber ZIP <input type="file" name="boards" accept=".zip" required></label></p>'
            '<p><label>Copies <input type="number" name="counts" value="1" min="1" max="200"></label></p>'
            '<p><label>Exposure time (s) <input type="number" name="exposure_s" value="120" min="1" max="3600">'
            "</label></p><p><button>Create job</button></p></form>"
            '<p>API: <a href="/docs">/docs</a></p>'
        )
        return _page("PCBHomeFab", body)

    @app.post("/jobs")
    async def post_job_form(
        request: Request,
        boards: Annotated[list[UploadFile], File()],
        counts: Annotated[list[int] | None, Form()] = None,
        exposure_s: Annotated[float, Form(ge=1, le=3600)] = 120.0,
    ) -> RedirectResponse:
        printer = PRINTERS["photon-m3"]
        options = {
            "printer": "photon-m3",
            "mill": "3018pro",
            "exposure": True,
            "mill_gcode": True,
            "exposure_s": exposure_s,
            "holes": "full",
            "gap_mm": 3.0,
            "margin_mm": 3.0,
            "flip": "x",
            "thickness_mm": 1.5,
            "tabs": True,
            "frame_left_mm": printer.frame_left_mm,
            "frame_bottom_mm": printer.frame_bottom_mm,
            "mirror_x": printer.mirror_x,
        }
        record = await create_job(request, boards, counts, options)
        return RedirectResponse(f"/jobs/{record.id}", status_code=303)

    return app
