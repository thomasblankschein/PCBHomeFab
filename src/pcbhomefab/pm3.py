"""Writing the Anycubic ``.pm3`` slice file (phase 1: through UVtools).

UVtools 7.1 cannot convert a single image and cannot edit a finished ``.pm3`` ("partial decoded").
The route that works is: Generic ZIP (``1.png`` + ``manifest.uvtools``) -> ``.uvj`` (parameters can be
set there) -> ``.pm3``. The machine name and height get lost on the way and are patched into the
``MACHINE`` table afterwards, because Photon Workshop rejects files whose printer is unknown.
A native writer will replace this module's UVtools calls.
"""

from __future__ import annotations

import io
import shutil
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from .errors import PCBHomeFabError
from .profiles import PrinterProfile

#: Size in bytes of the MACHINE table including its name and length fields.
MACHINE_TABLE_SIZE = 156
MACHINE_Z_MM = 180.0
LAYER_HEIGHT_MM = 0.05


class UVtoolsError(PCBHomeFabError):
    """UVtools is missing or a UVtools call failed."""


def find_uvtools() -> Path:
    """Locate ``UVtoolsCmd``."""
    found = shutil.which("UVtoolsCmd")
    candidates = [
        Path(r"C:\Program Files\UVtools\UVtoolsCmd.exe"),
        Path("/opt/UVtools/UVtoolsCmd"),
        Path("/usr/local/bin/UVtoolsCmd"),
    ]
    for candidate in ([Path(found)] if found else []) + candidates:
        if candidate.exists():
            return candidate
    raise UVtoolsError("UVtoolsCmd was not found. Install UVtools or put UVtoolsCmd on the PATH.")


def _run(uvtools: Path, *args: str) -> None:
    result = subprocess.run([str(uvtools), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise UVtoolsError(
            f"UVtools failed ({' '.join(args[:2])}): {result.stdout[-400:]}{result.stderr[-400:]}"
        )


def _generic_zip(mask: Image.Image, printer: PrinterProfile, layers: int, target: Path) -> None:
    png = io.BytesIO()
    mask.convert("L").save(png, "PNG")
    manifest = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f"<Manifest><LayerHeight>{LAYER_HEIGHT_MM}</LayerHeight>"
        f"<ResolutionX>{printer.resolution_x}</ResolutionX><ResolutionY>{printer.resolution_y}</ResolutionY>"
        f"<DisplayWidth>{printer.display_width_mm:.2f}</DisplayWidth>"
        f"<DisplayHeight>{printer.display_height_mm:.2f}</DisplayHeight>"
        f"<MachineZ>{MACHINE_Z_MM:g}</MachineZ></Manifest>"
    )
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for number in range(1, layers + 1):
            archive.writestr(f"{number}.png", png.getvalue())
        archive.writestr("manifest.uvtools", manifest)


def _machine_table(data: bytes) -> int:
    start = data.find(b"MACHINE" + bytes([0]))
    if start < 0 or struct.unpack_from("<I", data, start + 12)[0] != MACHINE_TABLE_SIZE:
        raise UVtoolsError("The MACHINE table was not found in the .pm3 file, unknown format.")
    return start


def copy_machine_table(pm3: Path, template: Path) -> None:
    """Take the whole MACHINE table from a file that Photon Workshop produced (safest way)."""
    target = bytearray(pm3.read_bytes())
    source = template.read_bytes()
    t, s = _machine_table(bytes(target)), _machine_table(source)
    target[t : t + MACHINE_TABLE_SIZE] = source[s : s + MACHINE_TABLE_SIZE]
    pm3.write_bytes(target)


def set_machine(pm3: Path, name: str, z_mm: float) -> None:
    """Write printer name and build height into the MACHINE table.

    Layout from the table name on: +16 machine name (96 bytes), +112 image format, +128 AA level,
    +136 display width, +140 display height, +144 build height (float).
    """
    encoded = name.encode("utf-8")
    if not 0 < len(encoded) < 96:
        raise UVtoolsError("The printer name is empty or too long.")
    data = bytearray(pm3.read_bytes())
    start = _machine_table(bytes(data))
    data[start + 16 : start + 112] = encoded.ljust(96, bytes([0]))
    struct.pack_into("<f", data, start + 144, z_mm)
    pm3.write_bytes(data)


def write_pm3(
    mask: Image.Image,
    printer: PrinterProfile,
    target: Path,
    exposure_s: float | None = None,
    layers: int = 1,
    template: Path | None = None,
) -> None:
    """Write ``target`` (.pm3) from the display mask.

    ``template`` is an optional ``.pm3`` file from Photon Workshop. Its print parameters (lift, speeds)
    and its machine table are taken over. Without it the printer name of the profile is used.
    """
    uvtools = find_uvtools()
    exposure = printer.default_exposure_s if exposure_s is None else exposure_s
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "mask.zip"
        uvj_path = Path(tmp) / "mask.uvj"
        _generic_zip(mask, printer, layers, zip_path)
        _run(uvtools, "convert", str(zip_path), "uvj", str(uvj_path))
        if template is not None:
            _run(uvtools, "copy-parameters", str(template), str(uvj_path))
        _run(
            uvtools,
            "set-properties",
            str(uvj_path),
            f"BottomLayerCount={layers}",
            f"ExposureTime={exposure:g}",
            f"BottomExposureTime={exposure:g}",
        )
        _run(uvtools, "convert", str(uvj_path), "pm3", str(target))
    if template is not None:
        copy_machine_table(target, template)
    else:
        set_machine(target, printer.machine_name, MACHINE_Z_MM)
