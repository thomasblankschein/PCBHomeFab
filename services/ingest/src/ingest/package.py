"""Reading a single-sided board from a Gerber ZIP and building the canonical board package.

The package is a ZIP with exactly ``copper.gbr`` (the bottom copper file as uploaded) and ``board.json``
(``contracts/schemas/board.schema.json``).
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import warnings
import zipfile
from pathlib import Path
from typing import Any

from gerbonara import ExcellonFile, GerberFile, LayerStack

from .common import Problem

#: Hard limits for uploaded archives (zip bombs, absurd uploads).
MAX_ZIP_FILES = 64
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)  # fixed, so the same upload always gives the same package


def _problem(code: str, detail: str) -> Problem:
    return Problem(422, code, detail)


def _check_zip(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise _problem("ingest.invalid_zip", "The upload is not a valid ZIP file.") from exc
    entries = archive.infolist()
    if len(entries) > MAX_ZIP_FILES:
        raise _problem("ingest.too_many_files", f"The ZIP contains more than {MAX_ZIP_FILES} files.")
    if sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
        raise _problem("ingest.too_large_unpacked", "The ZIP is too large when unpacked.")


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
        raise _problem("ingest.empty_outline", "The board outline layer (Edge.Cuts) is empty.")
    return min(xs), min(ys), max(xs), max(ys)


def _holes(stack: Any, xmin: float, ymin: float) -> list[dict[str, Any]]:
    holes: list[dict[str, Any]] = []
    for layer, plated in ((stack.drill_pth, True), (stack.drill_npth, False)):
        if layer is None:
            continue
        for obj in layer.objects:
            obj_mm = obj.converted("mm")
            if not hasattr(obj_mm, "x"):
                raise _problem("ingest.slots_unsupported", "Routed slots in the drill files are not supported yet.")
            holes.append(
                {
                    "x_mm": round(obj_mm.x - xmin, 4),
                    "y_mm": round(obj_mm.y - ymin, 4),
                    "diameter_mm": round(obj_mm.tool.diameter, 3),
                    "plated": plated,
                }
            )
    return holes


_FUNCTION = re.compile(r"%TF\.FileFunction,([^*]*)\*%|TF\.FileFunction,(\S+)")


def _file_function(text: str) -> str:
    match = _FUNCTION.search(text[:2000])
    return (match.group(1) or match.group(2)).lower() if match else ""


def _open_by_attributes(zip_path: Path, folder: Path) -> Any:
    """Assign the files to layers by their X2 ``FileFunction`` attribute (as written by KiCad)."""
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(folder)
    graphic: dict[tuple[str, str], Any] = {}
    pth = npth = None
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        text = path.read_text(errors="replace")
        function = _file_function(text)
        suffix = path.suffix.lower()
        if suffix in (".drl", ".xln", ".drd", ".txt") and "m48" in text[:200].lower():
            drill = ExcellonFile.open(path)
            if "nonplated" in function or "npth" in path.stem.lower():
                npth = drill
            else:
                pth = drill
        elif function.startswith("copper") and function.endswith("bot"):
            graphic[("bottom", "copper")] = GerberFile.open(path)
        elif function.startswith("profile"):
            graphic[("mechanical", "outline")] = GerberFile.open(path)
    return LayerStack(graphic_layers=graphic, drill_pth=pth, drill_npth=npth, board_name=zip_path.stem)


def build_package(data: bytes, name: str) -> bytes:
    """Read a Gerber ZIP and return the canonical board package (bytes of a ZIP)."""
    _check_zip(data)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "board.zip"
        zip_path.write_bytes(data)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                try:
                    stack = LayerStack.open(zip_path)
                except Exception:  # gerbonara cannot map the files of a ZIP with only a few layers
                    stack = _open_by_attributes(zip_path, Path(tmp) / "files")
            except Exception as exc:  # gerbonara raises many different types for broken input
                raise _problem(
                    "ingest.unreadable_gerber",
                    "The Gerber files could not be read. Send a ZIP with the bottom copper (B.Cu), "
                    "the board outline (Edge.Cuts) and the Excellon drill files.",
                ) from exc

        copper = stack.graphic_layers.get(("bottom", "copper"))
        if copper is None:
            raise _problem("ingest.no_copper", "No bottom copper layer (B.Cu) found in the ZIP.")
        if stack.outline is None:
            raise _problem("ingest.no_outline", "No board outline layer (Edge.Cuts) found in the ZIP.")
        xmin, ymin, xmax, ymax = _outline_bounds(stack.outline)
        holes = _holes(stack, xmin, ymin)
        copper_bytes = Path(copper.original_path).read_bytes()  # the file as uploaded, read before the folder goes

    width, height = round(xmax - xmin, 1), round(ymax - ymin, 1)
    if width <= 0 or height <= 0:
        raise _problem("ingest.empty_outline", "The board outline layer (Edge.Cuts) has no area.")
    board = {
        "schema_version": 1,
        "name": name,
        "outline": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
        "width_mm": width,
        "height_mm": height,
        "holes": holes,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for filename, content in (("copper.gbr", copper_bytes), ("board.json", json.dumps(board, indent=1).encode())):
            info = zipfile.ZipInfo(filename, _ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, content)
    return buffer.getvalue()
