"""Canonical board packages and layouts as the mill service reads them (contracts/schemas)."""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .common import Problem

BoardId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
_BOARD_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_BOARD_JSON_BYTES = 2 * 1024 * 1024
MAX_POINTS = 20000


class Hole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_mm: float
    y_mm: float
    diameter_mm: float = Field(gt=0)
    plated: bool


Polygon = Annotated[list[tuple[float, float]], Field(min_length=3, max_length=MAX_POINTS)]


class Contour(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outer: Polygon
    cutouts: list[Polygon] = Field(max_length=100)


class Board(BaseModel):
    """``board.json``. The mill needs the size and the holes, not the outline box or the copper."""

    model_config = ConfigDict(extra="ignore")
    schema_version: int
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    holes: list[Hole]
    contour: Contour | None = None


class Plate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)


class PlacementModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board_id: BoardId
    x_mm: float
    y_mm: float
    rotation_deg: int = Field(ge=0, le=0)


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plate: Plate
    placements: list[PlacementModel]


def board_id_of(filename: str) -> str:
    """Board id from a package file name ``<board_id>.zip``."""
    stem = filename.rsplit("/", 1)[-1].removesuffix(".zip")
    if not _BOARD_ID.match(stem):
        raise Problem(422, "common.invalid_request", f"'{filename}' is not named <board_id>.zip.")
    return stem


def read_board(package: bytes, board_id: str) -> Board:
    """``board.json`` of a canonical package (a ZIP with exactly ``copper.gbr`` and ``board.json``)."""
    invalid = Problem(422, "mill.invalid_package", f"The package of board '{board_id}' is not a canonical package.")
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            if sorted(archive.namelist()) != ["board.json", "copper.gbr"]:
                raise invalid
            if archive.getinfo("board.json").file_size > MAX_BOARD_JSON_BYTES:
                raise invalid
            board = Board.model_validate(json.loads(archive.read("board.json")))
    except (zipfile.BadZipFile, json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
        raise invalid from exc
    if board.schema_version != 1:
        raise invalid
    return board
