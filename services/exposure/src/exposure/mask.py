"""Exposure mask for the resin printer.

Polarity for positive photoresist: **white = UV light passes = exposed = copper is etched away**,
black = light is blocked = copper stays. Copper (traces, pads, pours) is therefore black.
"""

from __future__ import annotations

from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .boards import Board, Mark, Placement
from .profiles import PrinterProfile
from .raster import rasterize_copper

#: Diameter of the center mark that guides the drill (mode "center"), in mm.
CENTER_MARK_MM = 0.4
#: Resolution and colour of the copper picture used by the 3D view of the user interface.
COPPER_PX_MM = 0.1
COPPER_RGB = (214, 138, 62)

#: Positioning mark: two quarter circles of copper that face each other diagonally, inside a free (etched) disc. The
#: tips of the quarter circles meet at the centre, and it stays there when too much is etched (both shrink the same
#: way).
MARK_PAD_MM = 2.4
#: Free ring around the copper circle, so that the mark is no part of a copper pour.
MARK_CLEARANCE_MM = 0.5
#: Text next to a mark (the G-code coordinates of the mark): height of the font and the
#: gap between the free ring of the mark and the first letter.
#: Font of the label: DejaVu Sans Mono Bold, equal width and thick strokes (licence next to it).
LABEL_FONT = Path(__file__).parent / "data" / "fonts" / "DejaVuSansMono-Bold.ttf"
LABEL_SIZE_MM = 2.0
LABEL_GAP_MM = 0.2
#: Outer size of a mark with its free ring (the jobs service keeps the boards away from it).
MARK_FOOTPRINT_MM = MARK_PAD_MM + 2 * MARK_CLEARANCE_MM


#: The mark is drawn this many times larger and scaled down, which gives round edges and exact quadrants.
_MARK_SUPERSAMPLING = 8


def draw_mark(image: Image.Image, cx: float, cy: float, pixel_mm: float, voids: str, copper: int, clear: int) -> None:
    """Draw one positioning mark with its centre at pixel (cx, cy), in place. ``copper`` and ``clear`` are the grey
    values of copper and of etched-free area in this image. ``voids`` names the two quadrants without copper."""
    radius = MARK_PAD_MM / 2 / pixel_mm
    ring = (MARK_PAD_MM / 2 + MARK_CLEARANCE_MM) / pixel_mm
    size = 2 * ceil(ring)  # even, so that the centre of the tile lies on a pixel boundary
    big, middle = size * _MARK_SUPERSAMPLING, size * _MARK_SUPERSAMPLING / 2
    disc = Image.new("L", (big, big), 0)
    ImageDraw.Draw(disc).ellipse(
        [
            middle - ring * _MARK_SUPERSAMPLING,
            middle - ring * _MARK_SUPERSAMPLING,
            middle + ring * _MARK_SUPERSAMPLING,
            middle + ring * _MARK_SUPERSAMPLING,
        ],
        fill=255,
    )
    quarters = Image.new("L", (big, big), 0)
    box = [
        middle - radius * _MARK_SUPERSAMPLING,
        middle - radius * _MARK_SUPERSAMPLING,
        middle + radius * _MARK_SUPERSAMPLING,
        middle + radius * _MARK_SUPERSAMPLING,
    ]
    # PIL angles run clockwise from the right: 0-90 is bottom right, 90-180 bottom left, 180-270 top left, 270-360
    # top right
    spans = [(0, 90), (180, 270)] if voids == "tr-bl" else [(90, 180), (270, 360)]
    for start, end in spans:
        ImageDraw.Draw(quarters).pieslice(box, start, end, fill=255)
    corner = (round(cx) - size // 2, round(cy) - size // 2)
    image.paste(clear, corner, disc.resize((size, size), Image.Resampling.BOX))
    image.paste(copper, corner, quarters.resize((size, size), Image.Resampling.BOX))


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


def draw_label(image: Image.Image, cx: float, cy: float, pixel_mm: float, mark: Mark, value: int) -> None:
    """Write the label of ``mark`` next to its centre at pixel (cx, cy), in place, in the grey value ``value``.

    The text is mirrored like the plate is turned over for milling (``label_flip``), so it reads correctly on the
    finished copper. The block of text keeps its place, only the letters inside are mirrored."""
    if not mark.label:
        return
    font = ImageFont.truetype(str(LABEL_FONT), max(6, round(LABEL_SIZE_MM / pixel_mm)))
    left, top, right, bottom = font.getbbox(mark.label)
    text = Image.new("L", (ceil(right - left), ceil(bottom - top)), 0)
    ImageDraw.Draw(text).text((-left, -top), mark.label, fill=255, font=font)
    if mark.label_flip == "x":
        text = ImageOps.mirror(text)
    elif mark.label_flip == "y":
        text = ImageOps.flip(text)
    gap = (MARK_PAD_MM / 2 + MARK_CLEARANCE_MM + LABEL_GAP_MM) / pixel_mm
    x = cx + gap if mark.label_side == "right" else cx - gap - text.width
    image.paste(value, (round(x), round(cy - text.height / 2)), text)


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
        cx, cy = mark.x_mm / pixel, (plate_height_mm - mark.y_mm) / pixel
        draw_mark(alpha, cx, cy, pixel, mark.voids, 255, 0)
        draw_label(alpha, cx, cy, pixel, mark, 255)
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
        # the margin stays copper, so the letters are exposed (etched free) there
        draw_label(mask, cx, cy, pixel, mark, 255)
    if printer.mirror_x:
        mask = ImageOps.mirror(mask)
    return mask.point(lambda v: 255 if v >= 128 else 0).convert("1")
