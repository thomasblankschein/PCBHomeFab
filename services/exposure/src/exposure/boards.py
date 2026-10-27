"""Canonical board packages and layouts as the exposure service reads them (contracts/schemas)."""

from __future__ import annotations

import io
import json
import re
import tempfile
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from gerbonara import GerberFile
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .common import Problem

BoardId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
_BOARD_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_BOARD_JSON_BYTES = 2 * 1024 * 1024
MAX_COPPER_BYTES = 50 * 1024 * 1024


# --- request models ----------------------------------------------------------------------------------------


class Outline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    xmin: float
    ymin: float
    xmax: float
    ymax: float


class HoleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_mm: float
    y_mm: float
    diameter_mm: float = Field(gt=0)
    plated: bool


class BoardModel(BaseModel):
    """``board.json``."""

    model_config = ConfigDict(extra="ignore")
    schema_version: int
    outline: Outline
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    holes: list[HoleModel]


class MarkModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_mm: float
    y_mm: float
    voids: Literal["tl-br", "tr-bl"] = "tl-br"
    label: str | None = Field(default=None, min_length=1, max_length=20)
    label_flip: Literal["none", "x", "y"] = "none"
    label_side: Literal["right", "left"] = "right"


class PlateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)


class PlacementModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board_id: BoardId
    x_mm: float
    y_mm: float
    rotation_deg: int = Field(ge=0, le=0)


class LayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plate: PlateModel
    placements: list[PlacementModel]


# --- boards in memory --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hole:
    """A round hole, position relative to the lower left corner of the board outline (Y up, mm)."""

    x: float
    y: float
    diameter: float
    plated: bool


@dataclass
class Board:
    """One single-sided board: bottom copper, outline box and drill holes.

    Coordinates of the copper file are kept as they are (Y up, mm). ``xmin``/``ymax`` locate the board outline so
    that the copper layer can be rasterized in top view.
    """

    name: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    width_mm: float
    height_mm: float
    copper: Any  # gerbonara.GerberFile
    holes: list[Hole] = field(default_factory=list)


@dataclass(frozen=True)
class Placement:
    """A board at a position on the plate (lower left corner of the board, plate origin at its lower left)."""

    board: Board
    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class Mark:
    """A positioning mark: centre in plate coordinates and which two quadrants are etched free."""

    x_mm: float
    y_mm: float
    voids: str = "tl-br"
    label: str | None = None
    label_flip: str = "none"
    label_side: str = "right"


def board_id_of(filename: str) -> str:
    """Board id from a package file name ``<board_id>.zip``."""
    stem = filename.rsplit("/", 1)[-1].removesuffix(".zip")
    if not _BOARD_ID.match(stem):
        raise Problem(422, "common.invalid_request", f"'{filename}' is not named <board_id>.zip.")
    return stem


def load_board(package: bytes, board_id: str) -> Board:
    """Read a canonical package (a ZIP with exactly ``copper.gbr`` and ``board.json``)."""
    invalid = Problem(422, "exposure.invalid_package", f"The package of board '{board_id}' is not a canonical package.")
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            if sorted(archive.namelist()) != ["board.json", "copper.gbr"]:
                raise invalid
            if archive.getinfo("board.json").file_size > MAX_BOARD_JSON_BYTES:
                raise invalid
            if archive.getinfo("copper.gbr").file_size > MAX_COPPER_BYTES:
                raise invalid
            meta = BoardModel.model_validate(json.loads(archive.read("board.json")))
            copper_bytes = archive.read("copper.gbr")
    except (zipfile.BadZipFile, json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
        raise invalid from exc
    if meta.schema_version != 1:
        raise invalid
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "copper.gbr"
        path.write_bytes(copper_bytes)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                copper = GerberFile.open(path)
            except Exception as exc:  # gerbonara raises many different types for broken input
                raise Problem(
                    422, "exposure.unreadable_copper", f"The copper file of board '{board_id}' could not be read."
                ) from exc
    return Board(
        name=board_id,
        xmin=meta.outline.xmin,
        ymin=meta.outline.ymin,
        xmax=meta.outline.xmax,
        ymax=meta.outline.ymax,
        width_mm=meta.width_mm,
        height_mm=meta.height_mm,
        copper=copper,
        holes=[Hole(h.x_mm, h.y_mm, h.diameter_mm, h.plated) for h in meta.holes],
    )
