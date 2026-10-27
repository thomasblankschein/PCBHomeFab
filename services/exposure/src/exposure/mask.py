"""Exposure mask for the resin printer.

Polarity for positive photoresist: **white = UV light passes = exposed = copper is etched away**,
black = light is blocked = copper stays. Copper (traces, pads, pours) is therefore black.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageOps

from .boards import Board, Mark, Placement
from .profiles import PrinterProfile
from .raster import rasterize_copper

#: Diameter of the center mark that guides the drill (mode "center"), in mm.
CENTER_MARK_MM = 0.4
#: Resolution and colour of the copper picture used by the 3D view of the user interface.
COPPER_PX_MM = 0.1
COPPER_RGB = (214, 138, 62)

#: Positioning mark: a copper square with two diagonal quadrants etched free, inside a free ring. Where the two free
#: quadrants touch is the centre, and it stays there when too much is etched (both squares grow the same way).
MARK_PAD_MM = 2.4
#: Width of the copper border around the two free quadrants, as a share of the pad.
MARK_BORDER = 0.06
#: Free ring around the pad, so that the pad is no part of a copper pour.
MARK_CLEARANCE_MM = 0.5
MARK_CORNER_MM = 0.2
#: Outer size of a mark with its free ring (the jobs service keeps the boards away from it).
MARK_FOOTPRINT_MM = MARK_PAD_MM + 2 * MARK_CLEARANCE_MM


def draw_mark(image: Image.Image, cx: float, cy: float, pixel_mm: float, voids: str, copper: int, clear: int) -> None:
    """Draw one positioning mark with its centre at pixel (cx, cy), in place. ``copper`` and ``clear`` are the grey
    values of copper and of etched-free area in this image."""
    draw = ImageDraw.Draw(image)
    half = MARK_PAD_MM / 2 / pixel_mm
    ring = (MARK_PAD_MM / 2 + MARK_CLEARANCE_MM) / pixel_mm
    border = MARK_BORDER * MARK_PAD_MM / pixel_mm
    corner = MARK_CORNER_MM / pixel_mm
    # the centre lies on a pixel boundary, so that the two free squares touch exactly there
    x, y = round(cx), round(cy)
    draw.rounded_rectangle([x - ring, y - ring, x + ring - 1, y + ring - 1], radius=corner, fill=clear)
    draw.rounded_rectangle([x - half, y - half, x + half - 1, y + half - 1], radius=corner, fill=copper)
    low, high = round(half - border), round(half - border)
    left, right = (x - low, x - 1), (x, x + high - 1)
    top, bottom = (y - low, y - 1), (y, y + high - 1)
    squares = [(right, top), (left, bottom)] if voids == "tr-bl" else [(left, top), (right, bottom)]
    for (x0, x1), (y0, y1) in squares:
        draw.rectangle([x0, y0, x1, y1], fill=clear)


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


def build_copper(
    placements: list[Placement], plate_width_mm: float, plate_height_mm: float, marks: list[Mark] | None = None
) -> Image.Image:
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
    for mark in marks or []:
        draw_mark(alpha, mark.x_mm / pixel, (plate_height_mm - mark.y_mm) / pixel, pixel, mark.voids, 255, 0)
    picture = Image.new("RGBA", alpha.size, (*COPPER_RGB, 0))
    picture.putalpha(alpha)
    return picture


def build_mask(
    placements: list[Placement], printer: PrinterProfile, holes: str = "full", marks: list[Mark] | None = None
) -> Image.Image:
    """Full display image (mode ``1``): boards on a black background, mirrored if the profile says so.

    ``holes`` controls how drill holes appear in the pads, see :func:`punch_holes`. ``marks`` are positioning marks.
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
    for mark in marks or []:
        cx = (printer.frame_left_mm + mark.x_mm) / pixel
        cy = (printer.display_height_mm - printer.frame_bottom_mm - mark.y_mm) / pixel
        draw_mark(mask, cx, cy, pixel, mark.voids, copper=0, clear=255)
    if printer.mirror_x:
        mask = ImageOps.mirror(mask)
    return mask.point(lambda v: 255 if v >= 128 else 0).convert("1")
