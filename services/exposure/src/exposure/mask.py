"""Exposure mask for the resin printer.

Polarity for positive photoresist: **white = UV light passes = exposed = copper is etched away**,
black = light is blocked = copper stays. Copper (traces, pads, pours) is therefore black.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageOps

from .boards import Board, Placement
from .profiles import PrinterProfile
from .raster import rasterize_copper

#: Diameter of the center mark that guides the drill (mode "center"), in mm.
CENTER_MARK_MM = 0.4
#: Resolution and colour of the copper picture used by the 3D view of the user interface.
COPPER_PX_MM = 0.1
COPPER_RGB = (214, 138, 62)


def punch_holes(no_copper: Image.Image, board: Board, px_mm: float, mode: str) -> None:
    """Expose the drill holes so the copper around them is etched away (drilling aid), in place.

    ``mode``: ``"full"`` removes copper over the whole drill diameter, ``"center"`` only a small mark,
    ``"none"`` leaves the pads solid.
    """
    if mode == "none":
        return
    if mode not in ("full", "center"):
        raise ValueError(f"Unknown hole mode: {mode}")
    draw = ImageDraw.Draw(no_copper)
    for hole in board.holes:
        radius = (hole.diameter if mode == "full" else CENTER_MARK_MM) / 2 / px_mm
        cx, cy = hole.x / px_mm, (board.height_mm - hole.y) / px_mm
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=255)


def build_copper(placements: list[Placement], plate_width_mm: float, plate_height_mm: float) -> Image.Image:
    """The copper of all boards on the plate, in top view (design view, X to the right, Y up), as an RGBA picture:
    copper colour where there is copper, transparent elsewhere. The drill holes are open. Not mirrored.
    """
    pixel = COPPER_PX_MM
    alpha = Image.new("L", (round(plate_width_mm / pixel), round(plate_height_mm / pixel)), 0)
    cache: dict[int, Image.Image] = {}
    for placement in placements:
        key = id(placement.board)
        if key not in cache:
            no_copper = ImageOps.invert(rasterize_copper(placement.board, px_mm=pixel))
            punch_holes(no_copper, placement.board, pixel, "full")
            cache[key] = ImageOps.invert(no_copper)
        alpha.paste(
            cache[key],
            (
                round(placement.x_mm / pixel),
                round((plate_height_mm - placement.y_mm - placement.board.height_mm) / pixel),
            ),
        )
    picture = Image.new("RGBA", alpha.size, (*COPPER_RGB, 0))
    picture.putalpha(alpha)
    return picture


def build_mask(placements: list[Placement], printer: PrinterProfile, holes: str = "full") -> Image.Image:
    """Full display image (mode ``1``): boards on a black background, mirrored if the profile says so.

    ``holes`` controls how drill holes appear in the pads, see :func:`punch_holes`.
    """
    pixel = printer.pixel_mm
    mask = Image.new("L", (printer.resolution_x, printer.resolution_y), 0)
    cache: dict[int, Image.Image] = {}
    for placement in placements:
        key = id(placement.board)
        if key not in cache:
            copper = rasterize_copper(placement.board, px_mm=pixel)
            no_copper = ImageOps.invert(copper)  # white where there is no copper
            punch_holes(no_copper, placement.board, pixel, holes)
            cache[key] = no_copper
        left = round((printer.frame_left_mm + placement.x_mm) / pixel)
        top = round(
            (printer.display_height_mm - printer.frame_bottom_mm - placement.y_mm - placement.board.height_mm) / pixel
        )
        mask.paste(cache[key], (left, top))
    if printer.mirror_x:
        mask = ImageOps.mirror(mask)
    return mask.point(lambda v: 255 if v >= 128 else 0).convert("1")
