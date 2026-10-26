"""The panel service: boards and counts in, placements on the plate out. A pure function, no state."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from . import common
from .common import Isolation, Problem
from .layout import BoardSpec, pack

BoardId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")]


class Plate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)


class BoardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: BoardId
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    count: int = Field(ge=1)


class LayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plate: Plate
    gap_mm: float = Field(default=3.0, ge=0)
    margin_mm: float = Field(default=3.0, ge=0)
    boards: list[BoardRequest] = Field(min_length=1)


@dataclass(frozen=True)
class Settings:
    #: Number of boards on one plate, copies included.
    max_boards: int = 500
    timeout_s: float = 10.0
    max_parallel: int = 8
    isolate: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            max_boards=common.env_int("MAX_BOARDS", 500),
            timeout_s=common.env_float("REQUEST_TIMEOUT_S", 10),
            max_parallel=common.env_int("MAX_PARALLEL", 8),
            isolate=os.environ.get("ISOLATE", "1") != "0",
        )


def _layout(request: dict[str, Any]) -> dict[str, Any]:
    plate = request["plate"]
    boards = [BoardSpec(b["id"], b["width_mm"], b["height_mm"], b["count"]) for b in request["boards"]]
    placements = pack(boards, plate["width_mm"], plate["height_mm"], request["gap_mm"], request["margin_mm"])
    return {
        "plate": plate,
        "placements": [{"board_id": p.board_id, "x_mm": p.x_mm, "y_mm": p.y_mm, "rotation_deg": 0} for p in placements],
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    isolation = Isolation(settings.timeout_s, settings.max_parallel, settings.isolate)
    app = FastAPI(title="PCBHomeFab panel", version="1.0.0")
    common.install(app, "panel")
    app.state.isolation = isolation

    @app.post("/v1/layouts")
    async def create_layout(request: LayoutRequest) -> dict[str, Any]:
        if sum(b.count for b in request.boards) > settings.max_boards:
            raise Problem(422, "common.invalid_request", f"At most {settings.max_boards} boards fit in one layout.")
        result: dict[str, Any] = await run_in_threadpool(isolation.run, _layout, request.model_dump())
        return result

    return app
