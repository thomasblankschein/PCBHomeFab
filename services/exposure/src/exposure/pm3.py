"""Reading and writing the Anycubic ``.pm3`` slice file (format version 516), without UVtools.

Layout (integers little endian, every table starts with a 12 byte name and a 4 byte length)::

    file mark   "ANYCUBIC", version, number of tables, then the addresses of the tables below
    HEADER      print parameters (exposure, lift, resolution, ...)
    PREVIEW     224 x 168 thumbnail, RGB565
    color table grey levels of the layer images (all 255 without anti-aliasing)
    LAYERDEF    32 bytes per layer: image address and length, lift, exposure, height, pixel count
    EXTRA       lift/retract parameters in two stages
    MACHINE     printer name and display data. Photon Workshop rejects unknown printer names
    layer images, run length encoded ("pw0Img")

Layer image encoding: the image is read row by row, one byte per pixel, only the high nibble counts. Runs of
the same nibble are stored as one byte ``nibble << 4 | length`` (length up to 15) or, for black (0) and white
(15), as two bytes ``nibble << 12 | length`` (length up to 4095). This module only writes black and white
images, the reader also understands grey levels.

The format was worked out from the open source UVtools implementation and is checked by reading the files
back with UVtools and by comparing the machine table with a file written by Photon Workshop.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .profiles import PrinterProfile

VERSION = 516
FILE_MARK_SIZE = 52
EXTRA_BODY_SIZE = 56
MACHINE_TABLE_SIZE = 156
PREVIEW_SIZE = (224, 168)
LAYER_HEIGHT_MM = 0.05
MAX_RUN = 4095
_PIXEL_SIZE_UM = 40.0

_RUNS = re.compile(rb"\x00+|\xff+")


class Pm3Error(Exception):
    """The ``.pm3`` data is invalid or has an unsupported format."""


def _table(name: bytes, body: bytes, length: int | None = None) -> bytes:
    """A named table: 12 byte name, 4 byte length, body. ``length`` defaults to the length of the body."""
    return name.ljust(12, b"\0") + struct.pack("<I", len(body) if length is None else length) + body


# --- layer image run length encoding -----------------------------------------------------------------------


def encode_layer(mask: Image.Image) -> tuple[bytes, int]:
    """Encode a black/white image. Returns the encoded bytes and the number of white pixels."""
    data = mask.convert("L").point(lambda v: 255 if v >= 128 else 0).tobytes()
    out = bytearray()
    white = 0
    for run in _RUNS.finditer(data):
        length = run.end() - run.start()
        color = 0xF if data[run.start()] else 0
        if color:
            white += length
        while length:
            step = min(length, MAX_RUN)
            out += ((color << 12) | step).to_bytes(2, "big")
            length -= step
    return bytes(out), white


def decode_layer(encoded: bytes, width: int, height: int) -> Image.Image:
    """Decode a layer image (grey levels included) into an ``L`` image."""
    total = width * height
    pixels = bytearray(total)
    position = 0
    index = 0
    while index < len(encoded) and position < total:
        byte = encoded[index]
        code, repeat = byte >> 4, byte & 0xF
        if code in (0x0, 0xF):
            if index + 1 >= len(encoded):
                repeat = total - position
            else:
                index += 1
                repeat = (repeat << 8) + encoded[index]
            color = 255 if code else 0
        else:
            color = (code << 4) | code
        index += 1
        if position + repeat > total:
            raise Pm3Error("A layer image runs past its end.")
        if color:
            pixels[position : position + repeat] = bytes([color]) * repeat
        position += repeat
    if 0 < position < total:
        raise Pm3Error("A layer image ends too early.")
    return Image.frombytes("L", (width, height), bytes(pixels))


# --- preview -----------------------------------------------------------------------------------------------


def _preview(mask: Image.Image) -> bytes:
    """Thumbnail as RGB565 (grey)."""
    small = mask.convert("L").resize(PREVIEW_SIZE, Image.Resampling.BOX)
    table = [struct.pack("<H", ((g >> 3) << 11) | ((g >> 2) << 5) | (g >> 3)) for g in range(256)]
    return b"".join(table[g] for g in small.tobytes())


# --- tables ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PrintParameters:
    """Parameters that can be taken over from an existing file (everything but exposure and resolution)."""

    wait_before_cure_s: float
    lift_height_mm: float
    lift_speed_mms: float
    retract_speed_mms: float
    #: Raw body of the EXTRA table (two-stage lift parameters).
    extra_body: bytes
    #: Raw MACHINE table including name and length.
    machine_table: bytes


def _extra_body(printer: PrinterProfile) -> bytes:
    lift, up, down = printer.lift_height_mm, printer.lift_speed_mms, printer.retract_speed_mms
    stage = struct.pack("<I6f", 2, lift, up, down, 0.0, up, down)
    return stage + stage  # bottom layers, then normal layers


def _machine_table(printer: PrinterProfile) -> bytes:
    encoded_name = printer.machine_name.encode("utf-8")
    if not 0 < len(encoded_name) < 96:
        raise Pm3Error("The printer name is empty or too long.")
    body = (
        encoded_name.ljust(96, b"\0")
        + b"pw0Img".ljust(16, b"\0")
        + struct.pack(
            "<IIfffII",
            16,
            printer.machine_properties,
            printer.machine_display_width_mm,
            printer.machine_display_height_mm,
            printer.machine_z_mm,
            VERSION,
            printer.machine_background,
        )
    )
    return _table(b"MACHINE", body, MACHINE_TABLE_SIZE)


def _header_body(
    printer: PrinterProfile,
    params: PrintParameters | None,
    exposure_s: float,
    layers: int,
    print_time_s: int,
) -> bytes:
    wait = params.wait_before_cure_s if params else 0.0
    lift = params.lift_height_mm if params else printer.lift_height_mm
    up = params.lift_speed_mms if params else printer.lift_speed_mms
    down = params.retract_speed_mms if params else printer.retract_speed_mms
    return (
        struct.pack(
            "<10f",
            _PIXEL_SIZE_UM,
            LAYER_HEIGHT_MM,
            exposure_s,
            wait,
            exposure_s,
            float(layers),
            lift,
            up,
            down,
            0.0,  # volume in ml
        )
        + struct.pack("<3I", 1, printer.resolution_x, printer.resolution_y)
        + struct.pack("<2f", 0.0, 0.0)  # weight, price
        + b"$\0\0\0"
        + struct.pack("<5I", 0, print_time_s, 0, 0, 0)  # per layer settings, print time, transition layers x2, mode
    )


# --- writer ------------------------------------------------------------------------------------------------


def build_pm3(
    mask: Image.Image,
    printer: PrinterProfile,
    exposure_s: float | None = None,
    layers: int = 1,
    parameters: PrintParameters | None = None,
) -> bytes:
    """Build the bytes of a ``.pm3`` file with ``layers`` identical layers showing ``mask``."""
    if mask.size != (printer.resolution_x, printer.resolution_y):
        raise Pm3Error(f"The mask must be {printer.resolution_x} x {printer.resolution_y} pixels.")
    if layers < 1:
        raise Pm3Error("At least one layer is required.")
    exposure = printer.default_exposure_s if exposure_s is None else exposure_s

    encoded, white = encode_layer(mask)
    lift = parameters.lift_height_mm if parameters else printer.lift_height_mm
    up = parameters.lift_speed_mms if parameters else printer.lift_speed_mms
    down = parameters.retract_speed_mms if parameters else printer.retract_speed_mms
    print_time = round(layers * (exposure + lift / up + lift / down))

    header = _table(b"HEADER", _header_body(printer, parameters, exposure, layers, print_time))
    preview_data = _preview(mask)
    preview_body = struct.pack("<I", PREVIEW_SIZE[0]) + b"x".ljust(4, b"\0") + struct.pack("<I", PREVIEW_SIZE[1])
    preview = _table(b"PREVIEW", preview_body + preview_data, 16 + len(preview_body) + len(preview_data))
    color_table = struct.pack("<II", 0, 16) + b"\xff" * 16 + struct.pack("<I", 0)
    layer_table_length = 4 + 32 * layers
    extra = _table(b"EXTRA", parameters.extra_body if parameters else _extra_body(printer), 24)
    machine = parameters.machine_table if parameters else _machine_table(printer)

    header_address = FILE_MARK_SIZE
    preview_address = header_address + len(header)
    color_address = preview_address + len(preview)
    layer_def_address = color_address + len(color_table)
    extra_address = layer_def_address + 16 + layer_table_length
    machine_address = extra_address + len(extra)
    image_address = machine_address + len(machine)

    mark = b"ANYCUBIC".ljust(12, b"\0") + struct.pack(
        "<10I",
        VERSION,
        8,  # number of tables
        header_address,
        0,  # software table (version 517 and later)
        preview_address,
        color_address,
        layer_def_address,
        extra_address,
        machine_address,
        image_address,
    )

    entries = b"".join(
        struct.pack(
            "<IIffffII",
            image_address + index * len(encoded),
            len(encoded),
            lift,
            up,
            exposure,
            LAYER_HEIGHT_MM,
            white,
            0,
        )
        for index in range(layers)
    )
    layer_def = _table(b"LAYERDEF", struct.pack("<I", layers) + entries, layer_table_length)
    return mark + header + preview + color_table + layer_def + extra + machine + encoded * layers


def write_pm3(
    mask: Image.Image,
    printer: PrinterProfile,
    target: Path,
    exposure_s: float | None = None,
    layers: int = 1,
    template: Path | None = None,
) -> None:
    """Write ``target`` (.pm3) from the display mask.

    ``template`` is an optional ``.pm3`` file from Photon Workshop. Its lift/retract parameters and its
    machine table are taken over; otherwise the values of the printer profile are used.
    """
    parameters = read_parameters(template) if template is not None else None
    target.write_bytes(build_pm3(mask, printer, exposure_s, layers, parameters))


# --- reader ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pm3Info:
    """What :func:`read_pm3` finds in a file."""

    machine_name: str
    resolution: tuple[int, int]
    layer_count: int
    exposure_s: float
    bottom_exposure_s: float
    bottom_layers: int
    layer_height_mm: float
    lift_height_mm: float
    lift_speed_mms: float
    retract_speed_mms: float
    wait_before_cure_s: float
    first_layer: Image.Image


def _addresses(data: bytes) -> dict[str, int]:
    if len(data) < FILE_MARK_SIZE or data[:8] != b"ANYCUBIC":
        raise Pm3Error("Not an Anycubic slice file.")
    version, _tables, header, _software, _preview, _color, layer_def, extra, machine, images = struct.unpack_from(
        "<10I", data, 12
    )
    if version != VERSION:
        raise Pm3Error(f"Only file version {VERSION} is supported, the file has version {version}.")
    return {"header": header, "layer_def": layer_def, "extra": extra, "machine": machine, "images": images}


def read_parameters(path: Path) -> PrintParameters:
    """Take the print parameters and the machine table from a ``.pm3`` file (for use as a template)."""
    data = path.read_bytes()
    at = _addresses(data)
    body = at["header"] + 16  # body: pixel size, layer height, exposure, wait, bottom exposure, bottom layers, lift...
    (wait,) = struct.unpack_from("<f", data, body + 12)
    lift, up, down = struct.unpack_from("<3f", data, body + 24)
    extra = data[at["extra"] + 16 : at["extra"] + 16 + EXTRA_BODY_SIZE]
    machine = data[at["machine"] : at["machine"] + MACHINE_TABLE_SIZE]
    if len(extra) != EXTRA_BODY_SIZE or len(machine) != MACHINE_TABLE_SIZE:
        raise Pm3Error("The template file is truncated.")
    return PrintParameters(wait, lift, up, down, extra, machine)


def read_pm3(path: Path) -> Pm3Info:
    """Read the main values and the first layer image of a ``.pm3`` file."""
    data = path.read_bytes()
    at = _addresses(data)
    body = at["header"] + 16
    _pixel, layer_height, exposure, wait, bottom_exposure, bottom_layers, lift, up, down = struct.unpack_from(
        "<9f", data, body
    )
    width, height = struct.unpack_from("<2I", data, body + 44)
    machine_start = at["machine"]
    name = data[machine_start + 16 : machine_start + 112].split(b"\0")[0].decode("utf-8", "replace")
    (layer_count,) = struct.unpack_from("<I", data, at["layer_def"] + 16)
    address, length = struct.unpack_from("<2I", data, at["layer_def"] + 20)
    image = decode_layer(data[address : address + length], width, height)
    return Pm3Info(
        machine_name=name,
        resolution=(width, height),
        layer_count=layer_count,
        exposure_s=exposure,
        bottom_exposure_s=bottom_exposure,
        bottom_layers=int(bottom_layers),
        layer_height_mm=layer_height,
        lift_height_mm=lift,
        lift_speed_mms=up,
        retract_speed_mms=down,
        wait_before_cure_s=wait,
        first_layer=image,
    )
