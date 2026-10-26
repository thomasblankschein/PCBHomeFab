"""Running one job with the core library: exposure files and mill G-code from the uploaded boards."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image

from .. import gcode
from ..board import Board, load_board
from ..mask import build_mask
from ..panel import pack
from ..pm3 import write_pm3
from ..profiles import MILLS, PRINTERS, Plate
from ..tools import load_tools

CONTENT_TYPES = {
    ".png": "image/png",
    ".pm3": "application/octet-stream",
    ".nc": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
}
PREVIEW_SIZE = (1024, 640)


def _file_info(path: Path, relative: str) -> dict[str, Any]:
    return {
        "name": relative,
        "size": path.stat().st_size,
        "content_type": CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
    }


def run_job(job_dir: Path, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Read ``job_dir/input/*.zip`` as listed in ``params["boards"]`` and write the results to ``job_dir/output``.

    Returns the list of produced files (name relative to the output folder, size, content type).
    """
    printer = PRINTERS[params["printer"]]
    mill = MILLS[params["mill"]]
    printer = replace(
        printer,
        frame_left_mm=params["frame_left_mm"],
        frame_bottom_mm=params["frame_bottom_mm"],
        mirror_x=params["mirror_x"],
    )
    mill = replace(mill, flip=params["flip"], tabs=params["tabs"])
    plate = Plate(thickness_mm=params["thickness_mm"])

    loaded: dict[str, Board] = {}
    boards: list[Board] = []
    for entry in params["boards"]:
        if entry["file"] not in loaded:
            loaded[entry["file"]] = load_board(job_dir / "input" / entry["file"], name=entry["name"])
        boards += [loaded[entry["file"]]] * entry["count"]
    placements = pack(boards, plate, gap_mm=params["gap_mm"], margin_mm=params["margin_mm"])

    output = job_dir / "output"
    output.mkdir(exist_ok=True)
    files: list[Path] = []

    if params["exposure"]:
        mask = build_mask(placements, printer, holes=params["holes"])
        mask_path = output / "mask.png"
        mask.save(mask_path, dpi=(25.4 / printer.pixel_mm,) * 2)
        files.append(mask_path)
        preview = mask.convert("L").resize(PREVIEW_SIZE, Image.Resampling.BOX)
        preview_path = output / "mask_preview.png"
        preview.save(preview_path)
        files.append(preview_path)
        pm3_path = output / "exposure.pm3"
        write_pm3(mask, printer, pm3_path, exposure_s=params["exposure_s"])
        files.append(pm3_path)

    if params["mill_gcode"]:
        mill_dir = output / "mill"
        mill_dir.mkdir(exist_ok=True)
        programs = gcode.generate(placements, plate, mill, load_tools())
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for program in programs:
                path = mill_dir / program.filename
                path.write_text(program.code, encoding="ascii", errors="replace")
                files.append(path)
                bundle.writestr(program.filename, program.code)
        zip_path = output / "mill_gcode.zip"
        zip_path.write_bytes(archive.getvalue())
        files.append(zip_path)
        svg_path = output / "mill_preview.svg"
        svg_path.write_text(gcode.preview_svg(placements, plate, mill), encoding="utf-8")
        files.append(svg_path)

    return [_file_info(path, path.relative_to(output).as_posix()) for path in files]
