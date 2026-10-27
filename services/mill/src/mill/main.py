"""The mill service: board packages and a layout in, G-code programs out. No state."""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass, replace
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from . import common, gcode
from .boards import Board, Layout, board_id_of, read_board
from .common import Isolation, Problem
from .profiles import MILLS, Plate
from .tools import load_tools

_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class MarkModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_mm: float
    y_mm: float
    voids: Literal["tl-br", "tr-bl"] = "tl-br"
    # the text next to the mark is drawn by `exposure`, the mill only accepts the shared mark format
    label: str | None = Field(default=None, min_length=1, max_length=20)
    label_flip: Literal["none", "x", "y"] = "none"
    label_side: Literal["right", "left"] = "right"


class MillSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mill: str
    flip: Literal["x", "y", "none"] | None = None
    tabs: bool | None = None
    thickness_mm: float = Field(default=1.5, ge=0.4, le=3.2)
    marks: list[MarkModel] | None = Field(default=None, min_length=2, max_length=2)


@dataclass(frozen=True)
class Settings:
    max_package_bytes: int = 10 * 1024 * 1024
    max_packages: int = 16
    timeout_s: float = 60.0
    max_parallel: int = 4
    isolate: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            max_package_bytes=common.env_int("MAX_UPLOAD_MB", 10) * 1024 * 1024,
            max_packages=common.env_int("MAX_PACKAGES", 16),
            timeout_s=common.env_float("REQUEST_TIMEOUT_S", 60),
            max_parallel=common.env_int("MAX_PARALLEL", 4),
            isolate=os.environ.get("ISOLATE", "1") != "0",
        )


def _json(text: str, what: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise Problem(422, "common.invalid_request", f"The {what} is not valid JSON.") from exc


def _parse[T: BaseModel](model: type[T], text: str, what: str) -> T:
    try:
        return model.model_validate(_json(text, what))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise Problem(422, "common.invalid_request", f"Invalid {what} ({where}: {first['msg']}).") from exc


def _zip_entry(archive: zipfile.ZipFile, name: str, content: str | bytes) -> None:
    info = zipfile.ZipInfo(name, _ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content)


def _programs(boards: dict[str, Board], layout: dict[str, Any], settings: dict[str, Any]) -> bytes:
    """The ZIP with the programs. Runs in its own process."""
    mill = MILLS[settings["mill"]]
    if settings["flip"] is not None:
        mill = replace(mill, flip=settings["flip"])
    if settings["tabs"] is not None:
        mill = replace(mill, tabs=settings["tabs"])
    plate = Plate(layout["plate"]["width_mm"], layout["plate"]["height_mm"], settings["thickness_mm"])
    placements = []
    for item in layout["placements"]:
        board = boards[item["board_id"]]
        placements.append(
            gcode.Placement(
                item["x_mm"],
                item["y_mm"],
                board.width_mm,
                board.height_mm,
                [(h.x_mm, h.y_mm, h.diameter_mm) for h in board.holes],
                (list(board.contour.outer), [list(c) for c in board.contour.cutouts]) if board.contour else None,
                tuple((list(part.outer), [list(c) for c in part.cutouts]) for part in board.contour.others)
                if board.contour
                else (),
            )
        )
    second_mark = None
    if settings.get("marks"):
        mill, second_mark = gcode.origin_of_marks(plate, mill, [(m["x_mm"], m["y_mm"]) for m in settings["marks"]])
    programs = gcode.generate(placements, plate, mill, load_tools(), second_mark)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for program in programs:
            _zip_entry(archive, program.filename, program.code.encode("ascii", errors="replace"))
        _zip_entry(archive, "preview.svg", gcode.preview_svg(placements, plate, mill))
        index: dict[str, Any] = {
            "programs": [
                {
                    "filename": p.filename,
                    "title": p.title,
                    "tool": p.tool,
                    "holes": p.holes,
                    "outlines": p.outlines,
                }
                for p in programs
            ]
        }
        if second_mark is not None:
            index["marks"] = {"second_x_mm": round(second_mark[0], 3), "second_y_mm": round(second_mark[1], 3)}
        _zip_entry(archive, "programs.json", json.dumps(index, indent=1))
    return buffer.getvalue()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    isolation = Isolation(settings.timeout_s, settings.max_parallel, settings.isolate)
    app = FastAPI(title="PCBHomeFab mill", version="1.0.0")
    common.install(app, "mill")
    app.state.isolation = isolation

    @app.get("/v1/profiles")
    async def profiles() -> dict[str, Any]:
        plate = Plate()
        return {
            "mills": {
                key: {
                    "name": m.name,
                    "max_spindle_rpm": m.max_spindle_rpm,
                    "outline_endmill_mm": m.outline_endmill_mm,
                    "flip": m.flip,
                    "tabs": m.tabs,
                    "safe_z_mm": m.safe_z_mm,
                    "tool_change_z_mm": m.tool_change_z_mm,
                    "spindle_spinup_s": m.spindle_spinup_s,
                    "drill_overshoot_mm": m.drill_overshoot_mm,
                    "mill_overshoot_mm": m.mill_overshoot_mm,
                    "tab_width_mm": m.tab_width_mm,
                    "tab_height_mm": m.tab_height_mm,
                    "offset_x_mm": m.offset_x_mm,
                    "offset_y_mm": m.offset_y_mm,
                    "default_thickness_mm": plate.thickness_mm,
                }
                for key, m in MILLS.items()
            }
        }

    @app.get("/v1/tools")
    async def tools() -> dict[str, Any]:
        return load_tools().to_dict()

    @app.post("/v1/programs")
    async def create_programs(
        packages: Annotated[list[UploadFile], File()],
        layout: Annotated[str, Form()],
        settings_json: Annotated[str, Form(alias="settings")],
    ) -> Response:
        parsed_layout = _parse(Layout, layout, "layout")
        parsed_settings = _parse(MillSettings, settings_json, "settings")
        if parsed_settings.mill not in MILLS:
            known = ", ".join(sorted(MILLS))
            raise Problem(422, "mill.unknown_mill", f"Unknown mill profile '{parsed_settings.mill}' (known: {known}).")
        if not 1 <= len(packages) <= settings.max_packages:
            raise Problem(422, "common.invalid_request", f"Send between 1 and {settings.max_packages} packages.")
        boards: dict[str, Board] = {}
        for upload in packages:
            board_id = board_id_of(upload.filename or "")
            boards[board_id] = read_board(await common.read_limited(upload, settings.max_package_bytes), board_id)
        for placement in parsed_layout.placements:
            if placement.board_id not in boards:
                raise Problem(
                    422, "mill.unknown_board", f"The layout uses board '{placement.board_id}' without a package."
                )
        result: bytes = await run_in_threadpool(
            isolation.run, _programs, boards, parsed_layout.model_dump(), parsed_settings.model_dump()
        )
        return Response(
            result, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="programs.zip"'}
        )

    return app
