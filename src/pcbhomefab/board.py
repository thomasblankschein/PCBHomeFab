"""Reading a single-sided board from a Gerber ZIP."""

from __future__ import annotations

import io
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gerbonara import LayerStack

from .errors import InputError

#: Hard limits for uploaded archives (zip bombs, absurd uploads).
MAX_ZIP_FILES = 64
MAX_UNPACKED_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Hole:
    """A round hole, position relative to the lower left corner of the board outline (Y up, mm)."""

    x: float
    y: float
    diameter: float
    plated: bool


@dataclass
class Board:
    """One single-sided board: bottom copper, outline size and drill holes.

    Coordinates of the Gerber files are kept as they are (Y up, mm). ``xmin``/``ymax`` locate the board
    outline so that the copper layer can be rasterized in top view later.
    """

    name: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    copper: Any  # gerbonara.GerberFile
    holes: list[Hole] = field(default_factory=list)

    @property
    def width_mm(self) -> float:
        return round(self.xmax - self.xmin, 1)

    @property
    def height_mm(self) -> float:
        return round(self.ymax - self.ymin, 1)

    def hole_diameters(self) -> dict[float, int]:
        """Number of holes per diameter."""
        counts: dict[float, int] = {}
        for hole in self.holes:
            counts[hole.diameter] = counts.get(hole.diameter, 0) + 1
        return counts


def _check_zip(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InputError("The upload is not a valid ZIP file.") from exc
    entries = archive.infolist()
    if len(entries) > MAX_ZIP_FILES:
        raise InputError(f"The ZIP contains more than {MAX_ZIP_FILES} files.")
    if sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
        raise InputError("The ZIP is too large when unpacked.")


def _outline_bounds(outline: Any) -> tuple[float, float, float, float]:
    """Bounding box of the outline center lines (not of the drawn line width), in mm."""
    xs: list[float] = []
    ys: list[float] = []
    for obj in outline.objects:
        if hasattr(obj, "x1") and hasattr(obj, "x2"):
            obj_mm = obj.converted("mm")
            xs += [obj_mm.x1, obj_mm.x2]
            ys += [obj_mm.y1, obj_mm.y2]
        else:
            (x0, y0), (x1, y1) = obj.bounding_box("mm")
            xs += [x0, x1]
            ys += [y0, y1]
    if not xs:
        raise InputError("The board outline layer (Edge.Cuts) is empty.")
    return min(xs), min(ys), max(xs), max(ys)


def _holes(stack: Any, xmin: float, ymin: float) -> list[Hole]:
    holes: list[Hole] = []
    for layer, plated in ((stack.drill_pth, True), (stack.drill_npth, False)):
        if layer is None:
            continue
        for obj in layer.objects:
            obj_mm = obj.converted("mm")
            if not hasattr(obj_mm, "x"):
                raise InputError("Routed slots in the drill files are not supported yet.")
            holes.append(
                Hole(
                    x=round(obj_mm.x - xmin, 4),
                    y=round(obj_mm.y - ymin, 4),
                    diameter=round(obj_mm.tool.diameter, 3),
                    plated=plated,
                )
            )
    return holes


def load_board(source: bytes | str | Path, name: str | None = None) -> Board:
    """Read a Gerber ZIP (bytes or path) with bottom copper, outline and drill files."""
    if isinstance(source, bytes):
        data = source
    else:
        data = Path(source).read_bytes()
        name = name or Path(source).stem
    _check_zip(data)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "board.zip"
        zip_path.write_bytes(data)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                stack = LayerStack.open(zip_path)
            except Exception as exc:  # gerbonara raises many different types for broken input
                raise InputError(
                    "The Gerber files could not be read. Send a ZIP with the bottom copper (B.Cu), "
                    "the board outline (Edge.Cuts) and the Excellon drill files."
                ) from exc

    copper = stack.graphic_layers.get(("bottom", "copper"))
    if copper is None:
        raise InputError("No bottom copper layer (B.Cu) found in the ZIP.")
    if stack.outline is None:
        raise InputError("No board outline layer (Edge.Cuts) found in the ZIP.")
    xmin, ymin, xmax, ymax = _outline_bounds(stack.outline)
    return Board(
        name=name or stack.board_name or "board",
        xmin=xmin,
        ymin=ymin,
        xmax=xmax,
        ymax=ymax,
        copper=copper,
        holes=_holes(stack, xmin, ymin),
    )
