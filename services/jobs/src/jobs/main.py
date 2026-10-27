"""The jobs service: anonymous jobs with upload, queue, status and download.

There are no accounts. Creating a job returns a random id; the job link is the only credential. This service owns
all state (job database, input and output files) and runs the workflow over the other services.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
import threading
import time
import zipfile
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from . import common
from .common import Problem
from .config import Settings
from .marks import MIN_MARGIN_MM, MIN_PLATE_MM, alignment_marks
from .plates import PlateSize, load_plates
from .services import Services, Unavailable, UserError
from .store import DONE, JobRecord, JobStore
from .worker import worker_loop

JOB_ID = re.compile(r"^[A-Za-z0-9_-]{20,32}$")
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")
INLINE_TYPES = {"image/png", "image/svg+xml", "text/plain; charset=utf-8"}
PROFILE_ID = r"^[a-z0-9-]{1,40}$"


class PreviewBoard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
    width_mm: float = Field(gt=0, le=1000)
    height_mm: float = Field(gt=0, le=1000)
    count: int = Field(ge=1, le=1000)


class PreviewLayoutRequest(BaseModel):
    """Plate (id of a plate size), boards, copies and spacing of a job."""

    model_config = ConfigDict(extra="forbid")
    plate: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,40}$")]
    boards: list[PreviewBoard] = Field(min_length=1, max_length=50)
    gap_mm: float = Field(default=3.0, ge=0.5, le=20)
    margin_mm: float = Field(default=3.0, ge=0, le=20)


def _unavailable() -> Problem:
    return Problem(503, "jobs.upstream_unavailable", "A required service is not reachable. Try again later.")


def _client_hash(request: Request, settings: Settings) -> str:
    address = request.client.host if request.client else "unknown"
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        address = forwarded.split(",")[0].strip() or address
    return hashlib.sha256(f"{settings.ip_salt}:{address}".encode()).hexdigest()[:32]


def _job_json(record: JobRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "status": record.status,
        "created": record.created,
        "expires": record.expires,
        "error": record.error,
        "params": record.params,
        "files": record.files,
    }


def _unique_names(filenames: list[str]) -> list[str]:
    """Board ids from the file names: safe characters only, at most 40 characters, no duplicates."""
    names: list[str] = []
    for filename in filenames:
        base = SAFE_NAME.sub("_", Path(filename or "board.zip").stem)[:36] or "board"
        name, number = base, 1
        while name in names:
            number += 1
            name = f"{base}-{number}"
        names.append(name)
    return names


def _board_size(package: bytes) -> tuple[float, float]:
    """Width and height from ``board.json`` of a canonical package (the contract of ingest)."""
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            board = json.loads(archive.read("board.json"))
        return float(board["width_mm"]), float(board["height_mm"])
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as exc:
        raise _unavailable() from exc


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    services = services or Services(settings)
    store = JobStore(settings)
    plates = load_plates()
    stop = threading.Event()

    def find_plate(plate_id: str | None) -> PlateSize:
        found = plates.find(plate_id or "")
        if found is None:
            known = ", ".join(plate.id for plate in plates.active)
            raise Problem(422, "jobs.invalid_plate", f"Choose a plate size (one of: {known}).")
        return found

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        threads = [
            threading.Thread(
                target=worker_loop, args=(store, settings, services, stop), name=f"worker-{i}", daemon=True
            )
            for i in range(settings.workers)
        ]
        for thread in threads:
            thread.start()
        yield
        stop.set()
        for thread in threads:
            thread.join(timeout=5)

    app = FastAPI(title="PCBHomeFab jobs", version="1.0.0", lifespan=lifespan, root_path=settings.root_path)
    common.install(app, "jobs")
    app.state.store = store
    previews: dict[str, deque[float]] = defaultdict(deque)
    preview_lock = threading.Lock()

    def check_preview_rate(request: Request) -> None:
        """Previews cost a call to ingest or panel, so they get a limit of their own (kept in memory)."""
        client = _client_hash(request, settings)
        now = time.monotonic()
        with preview_lock:
            window = previews[client]
            while window and window[0] < now - 3600:
                window.popleft()
            if len(window) >= settings.preview_limit_per_hour:
                raise Problem(429, "jobs.rate_limited", "Too many requests. Try again later.", {"Retry-After": "600"})
            window.append(now)
            if len(previews) > 10000:  # forget clients that have been quiet for an hour
                for key in [k for k, w in previews.items() if not w or w[-1] < now - 3600]:
                    del previews[key]

    @app.get("/v1/tools")
    def tool_library() -> dict[str, Any]:
        try:
            return services.get_json(f"{settings.mill_url}/v1/tools", secrets.token_hex(6))
        except Unavailable as exc:
            raise _unavailable() from exc

    @app.get("/v1/plates")
    def plate_sizes() -> dict[str, Any]:
        return plates.to_dict()

    @app.get("/v1/profiles")
    def profiles() -> dict[str, Any]:
        request_id = secrets.token_hex(6)
        try:
            printers = services.get_json(f"{settings.exposure_url}/v1/profiles", f"{request_id}-exposure")
            mills = services.get_json(f"{settings.mill_url}/v1/profiles", f"{request_id}-mill")
        except Unavailable as exc:
            raise _unavailable() from exc
        return {
            "printers": printers["printers"],
            "mills": mills["mills"],
            "limits": {
                "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
                "max_files": settings.max_files,
                "max_boards": settings.max_boards,
                "job_ttl_hours": settings.job_ttl_s / 3600,
            },
        }

    @app.post("/v1/boards")
    async def board_info(request: Request, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        """Size, holes and contour of one uploaded Gerber ZIP, for the layout preview. Nothing is stored."""
        check_preview_rate(request)
        try:
            data = await common.read_limited(file, settings.max_upload_bytes)
        except Problem as exc:
            raise Problem(413, "jobs.upload_too_large", exc.detail) from exc
        [name] = _unique_names([file.filename or ""])
        try:
            package = await run_in_threadpool(services.ingest, data, name, f"{secrets.token_hex(6)}-ingest")
            with zipfile.ZipFile(io.BytesIO(package)) as archive:
                board: dict[str, Any] = json.loads(archive.read("board.json"))
        except UserError as exc:
            raise Problem(422, exc.code, exc.message) from exc
        except (Unavailable, zipfile.BadZipFile, KeyError, ValueError) as exc:
            raise _unavailable() from exc
        return board

    @app.post("/v1/layouts")
    def layout_preview(request: Request, body: PreviewLayoutRequest) -> dict[str, Any]:
        """Where the boards would sit on the plate. Asks the panel service, stores nothing."""
        check_preview_rate(request)
        if sum(b.count for b in body.boards) > settings.max_boards:
            raise Problem(422, "jobs.invalid_upload", f"At most {settings.max_boards} boards fit in one job.")
        plate = find_plate(body.plate)
        try:
            return services.panel(
                {
                    "plate": {"width_mm": plate.width_mm, "height_mm": plate.height_mm},
                    "gap_mm": body.gap_mm,
                    "margin_mm": body.margin_mm,
                    "boards": [b.model_dump() for b in body.boards],
                },
                f"{secrets.token_hex(6)}-panel",
            )
        except UserError as exc:
            raise Problem(422, exc.code, exc.message) from exc
        except Unavailable as exc:
            raise _unavailable() from exc

    @app.post("/v1/jobs", status_code=201)
    async def post_job(
        request: Request,
        boards: Annotated[list[UploadFile], File(description="Gerber ZIP files, one per board design")],
        counts: Annotated[list[int] | None, Form(description="Copies per file, same order")] = None,
        printer: Annotated[str, Form(pattern=PROFILE_ID)] = "photon-m3",
        mill: Annotated[str, Form(pattern=PROFILE_ID)] = "3018pro",
        exposure: Annotated[bool, Form()] = True,
        mill_gcode: Annotated[bool, Form()] = True,
        exposure_s: Annotated[float, Form(ge=1, le=3600)] = 120.0,
        holes: Annotated[Literal["full", "center", "none"], Form()] = "full",
        gap_mm: Annotated[float, Form(ge=0.5, le=20)] = 3.0,
        margin_mm: Annotated[float, Form(ge=0, le=20)] = 3.0,
        flip: Annotated[Literal["x", "y", "none"], Form()] = "x",
        thickness_mm: Annotated[float, Form(ge=0.4, le=3.2)] = 1.5,
        tabs: Annotated[bool, Form()] = True,
        frame_left_mm: Annotated[float | None, Form(ge=0, le=20)] = None,
        frame_bottom_mm: Annotated[float | None, Form(ge=0, le=20)] = None,
        mirror_x: Annotated[bool | None, Form()] = None,
        plate: Annotated[str | None, Form()] = None,
        marks: Annotated[bool, Form()] = True,
        mark_labels: Annotated[bool, Form()] = True,
    ) -> JSONResponse:
        client = _client_hash(request, settings)
        if store.recent_count(client) >= settings.rate_limit_per_hour:
            raise Problem(429, "jobs.rate_limited", "Too many jobs. Try again later.", {"Retry-After": "3600"})
        if store.queued_count() >= settings.max_queued:
            raise Problem(503, "jobs.queue_full", "The queue is full. Try again later.", {"Retry-After": "300"})
        if not boards or len(boards) > settings.max_files:
            raise Problem(422, "jobs.invalid_upload", f"Send between 1 and {settings.max_files} Gerber ZIP files.")
        counts = counts or [1] * len(boards)
        if len(counts) != len(boards) or any(c < 1 for c in counts):
            raise Problem(422, "jobs.invalid_upload", "Give one count (at least 1) for every file.")
        if sum(counts) > settings.max_boards:
            raise Problem(422, "jobs.invalid_upload", f"At most {settings.max_boards} boards fit in one job.")
        if not exposure and not mill_gcode:
            raise Problem(422, "jobs.invalid_upload", "Select at least one output (exposure or mill_gcode).")
        chosen_plate = find_plate(plate)
        if marks and margin_mm < MIN_MARGIN_MM:
            raise Problem(
                422, "jobs.invalid_marks", f"Positioning marks need a margin of at least {MIN_MARGIN_MM:g} mm."
            )
        if marks and min(chosen_plate.width_mm, chosen_plate.height_mm) < MIN_PLATE_MM:
            raise Problem(422, "jobs.invalid_marks", f"Positioning marks need a plate of at least {MIN_PLATE_MM:g} mm.")

        uploads: list[bytes] = []
        for upload in boards:
            try:
                uploads.append(await common.read_limited(upload, settings.max_upload_bytes))
            except Problem as exc:
                raise Problem(413, "jobs.upload_too_large", exc.detail) from exc
        names = _unique_names([upload.filename or "" for upload in boards])

        request_id = secrets.token_hex(6)
        packages: list[bytes] = []
        for name, data in zip(names, uploads, strict=True):
            try:
                packages.append(await run_in_threadpool(services.ingest, data, name, f"{request_id}-ingest"))
            except UserError as exc:
                raise Problem(422, exc.code, exc.message) from exc
            except Unavailable as exc:
                raise _unavailable() from exc

        job_id = secrets.token_urlsafe(16)
        job_dir = store.job_dir(job_id)
        (job_dir / "input").mkdir(parents=True)
        entries = []
        for index, (name, package, count) in enumerate(zip(names, packages, counts, strict=True)):
            width, height = _board_size(package)
            filename = f"board{index}.zip"
            (job_dir / "input" / filename).write_bytes(package)
            entries.append({"file": filename, "name": name, "count": count, "width_mm": width, "height_mm": height})
        params = {
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
            "plate": {"id": chosen_plate.id, "width_mm": chosen_plate.width_mm, "height_mm": chosen_plate.height_mm},
            "marks": alignment_marks(chosen_plate.width_mm, chosen_plate.height_mm, flip, mark_labels)
            if marks
            else None,
            "boards": entries,
        }
        record = store.create(job_id, params, client)
        return JSONResponse({"id": record.id, "status": record.status}, status_code=201)

    def _find(job_id: str) -> JobRecord:
        record = store.get(job_id) if JOB_ID.match(job_id) else None
        if record is None:
            raise Problem(404, "jobs.not_found", "Job not found or expired.")
        return record

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        return _job_json(_find(job_id))

    @app.get("/v1/jobs/{job_id}/files/{name:path}")
    async def get_file(job_id: str, name: str) -> FileResponse:
        record = _find(job_id)
        info = next((f for f in record.files if f["name"] == name), None)
        if record.status != DONE or info is None:
            raise Problem(404, "jobs.not_found", "File not found.")
        path = store.job_dir(job_id) / "output" / info["name"]
        disposition = "inline" if info["content_type"] in INLINE_TYPES else "attachment"
        return FileResponse(
            path,
            media_type=info["content_type"],
            filename=Path(info["name"]).name,
            content_disposition_type=disposition,
            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'"},
        )

    return app
