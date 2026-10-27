"""The exposure service: board packages and a layout in, exposure mask and slice file out. No state."""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass, replace
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, Response, UploadFile
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from . import common
from .boards import Board, LayoutModel, Mark, MarkModel, Placement, board_id_of, load_board
from .common import Isolation, Problem
from .mask import build_copper, build_mask
from .pm3 import build_pm3
from .profiles import PRINTERS

PREVIEW_SIZE = (1024, 640)
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ExposureSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    printer: str
    holes: Literal["full", "center", "none"] = "full"
    exposure_s: float = Field(default=120.0, ge=1, le=3600)
    frame_left_mm: float | None = Field(default=None, ge=0, le=20)
    frame_bottom_mm: float | None = Field(default=None, ge=0, le=20)
    mirror_x: bool | None = None
    marks: list[MarkModel] | None = Field(default=None, min_length=2, max_length=2)
    outputs: list[Literal["mask", "preview", "pm3", "copper"]] = Field(default=["mask", "preview", "pm3"], min_length=1)


@dataclass(frozen=True)
class Settings:
    max_package_bytes: int = 10 * 1024 * 1024
    max_packages: int = 16
    timeout_s: float = 120.0
    max_parallel: int = 2
    isolate: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            max_package_bytes=common.env_int("MAX_UPLOAD_MB", 10) * 1024 * 1024,
            max_packages=common.env_int("MAX_PACKAGES", 16),
            timeout_s=common.env_float("REQUEST_TIMEOUT_S", 120),
            max_parallel=common.env_int("MAX_PARALLEL", 2),
            isolate=os.environ.get("ISOLATE", "1") != "0",
        )


def _parse[T: BaseModel](model: type[T], text: str, what: str) -> T:
    try:
        return model.model_validate(json.loads(text))
    except json.JSONDecodeError as exc:
        raise Problem(422, "common.invalid_request", f"The {what} is not valid JSON.") from exc
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise Problem(422, "common.invalid_request", f"Invalid {what} ({where}: {first['msg']}).") from exc


def _zip_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, _ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content)


def _masks(packages: dict[str, bytes], layout: dict[str, Any], settings: dict[str, Any]) -> bytes:
    """The ZIP with the requested files. Runs in its own process."""
    printer = PRINTERS[settings["printer"]]
    overrides = {
        key: settings[key] for key in ("frame_left_mm", "frame_bottom_mm", "mirror_x") if settings[key] is not None
    }
    printer = replace(printer, **overrides)
    boards: dict[str, Board] = {board_id: load_board(data, board_id) for board_id, data in packages.items()}
    placements = [Placement(boards[p["board_id"]], p["x_mm"], p["y_mm"]) for p in layout["placements"]]

    outputs = settings["outputs"]
    marks = (
        [
            Mark(m["x_mm"], m["y_mm"], m["voids"], m["label"], m["label_flip"], m["label_side"])
            for m in settings["marks"]
        ]
        if settings.get("marks")
        else None
    )
    wants_mask = {"mask", "preview", "pm3"} & set(outputs)
    mask = build_mask(placements, printer, holes=settings["holes"], marks=marks) if wants_mask else None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if "copper" in outputs:
            plate = layout["plate"]
            png = io.BytesIO()
            build_copper(placements, plate["width_mm"], plate["height_mm"], marks).save(
                png, format="PNG", optimize=True
            )
            _zip_entry(archive, "copper.png", png.getvalue())
        if mask is not None and "mask" in outputs:
            png = io.BytesIO()
            mask.save(png, format="PNG", dpi=(25.4 / printer.pixel_mm,) * 2)
            _zip_entry(archive, "mask.png", png.getvalue())
        if mask is not None and "preview" in outputs:
            png = io.BytesIO()
            mask.convert("L").resize(PREVIEW_SIZE, Image.Resampling.BOX).save(png, format="PNG")
            _zip_entry(archive, "mask_preview.png", png.getvalue())
        if mask is not None and "pm3" in outputs:
            _zip_entry(archive, "exposure.pm3", build_pm3(mask, printer, settings["exposure_s"]))
    return buffer.getvalue()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    isolation = Isolation(settings.timeout_s, settings.max_parallel, settings.isolate)
    app = FastAPI(title="PCBHomeFab exposure", version="1.0.0")
    common.install(app, "exposure")
    app.state.isolation = isolation

    @app.get("/v1/profiles")
    async def profiles() -> dict[str, Any]:
        return {
            "printers": {
                key: {
                    "name": p.name,
                    "machine_name": p.machine_name,
                    "resolution": [p.resolution_x, p.resolution_y],
                    "display_mm": [p.display_width_mm, p.display_height_mm],
                    "pixel_mm": p.pixel_mm,
                    "frame_left_mm": p.frame_left_mm,
                    "frame_bottom_mm": p.frame_bottom_mm,
                    "mirror_x": p.mirror_x,
                    "default_exposure_s": p.default_exposure_s,
                    "lift_height_mm": p.lift_height_mm,
                    "lift_speed_mms": p.lift_speed_mms,
                    "retract_speed_mms": p.retract_speed_mms,
                }
                for key, p in PRINTERS.items()
            }
        }

    @app.post("/v1/masks")
    async def create_masks(
        packages: Annotated[list[UploadFile], File()],
        layout: Annotated[str, Form()],
        settings_json: Annotated[str, Form(alias="settings")],
    ) -> Response:
        parsed_layout = _parse(LayoutModel, layout, "layout")
        parsed_settings = _parse(ExposureSettings, settings_json, "settings")
        if parsed_settings.printer not in PRINTERS:
            known = ", ".join(sorted(PRINTERS))
            raise Problem(
                422, "exposure.unknown_printer", f"Unknown printer '{parsed_settings.printer}' (known: {known})."
            )
        printer = PRINTERS[parsed_settings.printer]
        left = printer.frame_left_mm if parsed_settings.frame_left_mm is None else parsed_settings.frame_left_mm
        bottom = printer.frame_bottom_mm if parsed_settings.frame_bottom_mm is None else parsed_settings.frame_bottom_mm
        plate = parsed_layout.plate
        if left + plate.width_mm > printer.display_width_mm or bottom + plate.height_mm > printer.display_height_mm:
            raise Problem(
                422,
                "exposure.plate_too_large",
                f"A {plate.width_mm:g} x {plate.height_mm:g} mm plate does not fit on the display of {printer.name} "
                f"({printer.display_width_mm:g} x {printer.display_height_mm:g} mm, "
                f"offsets {left:g} and {bottom:g} mm).",
            )
        if not 1 <= len(packages) <= settings.max_packages:
            raise Problem(422, "common.invalid_request", f"Send between 1 and {settings.max_packages} packages.")
        data: dict[str, bytes] = {}
        for upload in packages:
            data[board_id_of(upload.filename or "")] = await common.read_limited(upload, settings.max_package_bytes)
        for placement in parsed_layout.placements:
            if placement.board_id not in data:
                raise Problem(
                    422, "exposure.unknown_board", f"The layout uses board '{placement.board_id}' without a package."
                )
        result: bytes = await run_in_threadpool(
            isolation.run, _masks, data, parsed_layout.model_dump(), parsed_settings.model_dump()
        )
        return Response(
            result, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="masks.zip"'}
        )

    return app
