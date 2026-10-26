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


def draw_border(mask: Image.Image, printer: PrinterProfile) -> None:
    """Closed white frame of ``printer.border_mm`` along the outer edge of the whole display, in place."""
    if printer.border_mm <= 0:
        return
    width = max(1, round(printer.border_mm / printer.pixel_mm))
    ImageDraw.Draw(mask).rectangle([0, 0, mask.width - 1, mask.height - 1], outline=255, width=width)


def build_mask(placements: list[Placement], printer: PrinterProfile, holes: str = "full") -> Image.Image:
    """Full display image (mode ``1``): boards on a black background, mirrored if the profile says so.

    ``holes`` controls how drill holes appear in the pads, see :func:`punch_holes`. The border around the display is
    described in :func:`draw_border`.
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
    draw_border(mask, printer)
    if printer.mirror_x:
        mask = ImageOps.mirror(mask)
    return mask.point(lambda v: 255 if v >= 128 else 0).convert("1")
