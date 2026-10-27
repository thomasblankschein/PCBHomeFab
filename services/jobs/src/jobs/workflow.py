"""Running one job: ask the other services in order and store what they return."""

from __future__ import annotations

import io
import secrets
import time
import zipfile
from pathlib import Path
from typing import Any

from .services import Services, Unavailable, UserError

CONTENT_TYPES = {
    ".png": "image/png",
    ".pm3": "application/octet-stream",
    ".nc": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
}
#: The blank of jobs made before the plate size became a choice.
LEGACY_PLATE = {"width_mm": 160.0, "height_mm": 100.0}
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _file_info(path: Path, relative: str) -> dict[str, Any]:
    return {
        "name": relative,
        "size": path.stat().st_size,
        "content_type": CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
    }


def _write(path: Path, data: bytes, files: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    files.append(path)


def run_job(job_dir: Path, params: dict[str, Any], services: Services) -> list[dict[str, Any]]:
    """Read the board packages listed in ``params["boards"]`` from ``job_dir/input`` and write the results to
    ``job_dir/output``. Returns the produced files (name relative to the output folder, size, content type).
    """
    request_id = secrets.token_hex(6)
    deadline = time.monotonic() + services.settings.job_timeout_s

    def step(name: str) -> str:
        if time.monotonic() > deadline:
            raise UserError("jobs.timeout", f"The job took longer than {services.settings.job_timeout_s:g} seconds.")
        return f"{request_id}-{name}"

    entries = params["boards"]
    plate = params.get("plate") or LEGACY_PLATE
    packages = {e["name"]: (job_dir / "input" / e["file"]).read_bytes() for e in entries}

    layout = services.panel(
        {
            "plate": {"width_mm": plate["width_mm"], "height_mm": plate["height_mm"]},
            "gap_mm": params["gap_mm"],
            "margin_mm": params["margin_mm"],
            "boards": [
                {"id": e["name"], "width_mm": e["width_mm"], "height_mm": e["height_mm"], "count": e["count"]}
                for e in entries
            ],
        },
        step("panel"),
    )

    output = job_dir / "output"
    output.mkdir(exist_ok=True)
    files: list[Path] = []

    if params["exposure"]:
        settings: dict[str, Any] = {
            "printer": params["printer"],
            "holes": params["holes"],
            "exposure_s": params["exposure_s"],
            "outputs": ["mask", "preview", "pm3", "copper"],
        }
        for key in ("frame_left_mm", "frame_bottom_mm", "mirror_x"):
            if params.get(key) is not None:
                settings[key] = params[key]
        for name, data in services.exposure(packages, layout, settings, step("exposure")).items():
            _write(output / name, data, files)

    elif params["mill_gcode"]:
        # only for the 3D view of the user interface: a job without exposure does not fail when this does
        try:
            copper = services.exposure(
                packages,
                layout,
                {"printer": params["printer"], "holes": "full", "exposure_s": 1, "outputs": ["copper"]},
                step("copper"),
            )
        except (UserError, Unavailable):
            copper = {}
        for name, data in copper.items():
            _write(output / name, data, files)

    if params["mill_gcode"]:
        programs = services.mill(
            packages,
            layout,
            {
                "mill": params["mill"],
                "flip": params["flip"],
                "tabs": params["tabs"],
                "thickness_mm": params["thickness_mm"],
            },
            step("mill"),
        )
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name, data in sorted(programs.items()):
                if name.endswith(".nc"):
                    _write(output / "mill" / name, data, files)
                    info = zipfile.ZipInfo(name, _ZIP_TIME)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    bundle.writestr(info, data)
        _write(output / "mill_gcode.zip", archive.getvalue(), files)
        _write(output / "mill_preview.svg", programs["preview.svg"], files)

    return [_file_info(path, path.relative_to(output).as_posix()) for path in files]
