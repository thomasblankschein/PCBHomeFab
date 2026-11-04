"""Exposure series: one test exposure to find the right exposure time.

The panel is divided into ``steps`` strips side by side, each with the same test pattern. Exposure k lights the strips
1 to k, so strip 1 gets all exposures (the longest time) and the last strip only the last one (the shortest time). The
panel stays on the display for the whole series.

The Photon M3 exposes every layer for the time of the file header and ignores the time per layer (tried on the
printer). A longer exposure is therefore written as several equal layers of ``unit_s`` with the same image.

Polarity as in ``mask.py``: white = exposed = copper is etched away. The pattern is drawn as seen from the copper side
(text reads correctly on the etched board) and mirrored for the display like a mask of the bottom copper.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import gcd

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .mask import LABEL_FONT
from .profiles import PrinterProfile

#: Copper border around the panel and between the strips.
MARGIN_MM = 3.0
GAP_MM = 1.5
#: The pattern needs this width; narrower strips are refused.
MIN_STRIP_MM = 14.0
MAX_LAYERS = 200
#: Track and gap widths of the test rows.
LINE_WIDTHS_MM = (0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5)
#: SMD pad rows: pitch, pad width, pad height.
SMD_ROWS_MM = ((1.27, 0.6, 1.8), (0.8, 0.4, 1.5), (0.65, 0.35, 1.4), (0.5, 0.25, 1.2))
#: The pattern is drawn this many times finer than the display and scaled down.
SUPERSAMPLE = 2
#: Heights of the rows of the pattern and the gap between them.
LINE_ROW_MM = 2.6
THT_ROW_MM = 1.8
POUR_MM = 11.0
FINE_TEXT_MM = 5.6
ROW_GAP_MM = 1.0
#: Height of the labels in front of the rows and where the rows start after them.
LABEL_MM = 1.2
ROW_START_MM = 5.0


class SeriesError(Exception):
    """The values give no usable series. ``code`` and ``message`` are safe to show to users."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SeriesPlan:
    #: Total time of each strip, the first strip first (longest).
    section_s: list[int]
    #: Duration of each exposure; exposure k lights the strips 1 to k.
    exposure_s: list[int]
    unit_s: int
    print_time_s: int

    @property
    def layers_per_exposure(self) -> list[int]:
        return [d // self.unit_s for d in self.exposure_s]

    @property
    def layers(self) -> int:
        return sum(self.layers_per_exposure)

    def to_dict(self) -> dict[str, object]:
        """``series.json``, see ``contracts/schemas/exposure-series.schema.json``."""
        return {
            "unit_s": self.unit_s,
            "layers": self.layers,
            "print_time_s": self.print_time_s,
            "sections": [{"section": i + 1, "exposure_s": t} for i, t in enumerate(self.section_s)],
            "exposures": [
                {"exposure": k + 1, "sections": k + 1, "duration_s": d, "layers": n}
                for k, (d, n) in enumerate(zip(self.exposure_s, self.layers_per_exposure, strict=True))
            ],
        }


def plan_series(shortest_s: int, longest_s: int, steps: int, printer: PrinterProfile) -> SeriesPlan:
    """Times of the strips (evenly from ``longest_s`` to ``shortest_s``, whole seconds rounded half up), the
    exposures and the time of one layer."""
    if longest_s <= shortest_s:
        raise SeriesError("exposure.invalid_series", "The longest time must be longer than the shortest.")
    if longest_s - shortest_s < steps - 1:
        raise SeriesError(
            "exposure.invalid_series",
            f"{steps} steps need at least {steps - 1} seconds between the shortest and the longest time.",
        )
    span, divisions = longest_s - shortest_s, steps - 1
    # round half up with integers only: the frontend does the same and gets the same values
    section_s = [longest_s - (2 * i * span + divisions) // (2 * divisions) for i in range(steps)]
    exposure_s = [a - b for a, b in zip(section_s, section_s[1:], strict=False)] + [section_s[-1]]
    unit = 0
    for duration in exposure_s:
        unit = gcd(unit, duration)
    layers = longest_s // unit
    if layers > MAX_LAYERS:
        raise SeriesError(
            "exposure.series_too_many_layers",
            f"These times need {layers} layers of {unit} s (at most {MAX_LAYERS}). Choose rounder values, for "
            "example times and a range that are multiples of 5 or 10 seconds.",
        )
    move_s = printer.lift_height_mm / printer.lift_speed_mms + printer.lift_height_mm / printer.retract_speed_mms
    return SeriesPlan(section_s, exposure_s, unit, round(layers * (unit + move_s)))


def strip_width_mm(panel_width_mm: float, steps: int) -> float:
    return (panel_width_mm - 2 * MARGIN_MM - (steps - 1) * GAP_MM) / steps


def check_strips(panel_width_mm: float, steps: int) -> None:
    width = strip_width_mm(panel_width_mm, steps)
    if width < MIN_STRIP_MM:
        most = max(1, int((panel_width_mm - 2 * MARGIN_MM + GAP_MM) // (MIN_STRIP_MM + GAP_MM)))
        raise SeriesError(
            "exposure.invalid_series",
            f"{steps} strips are {width:.1f} mm wide on this panel, the pattern needs {MIN_STRIP_MM:g} mm. "
            f"Use at most {most} steps.",
        )


# --- the test pattern --------------------------------------------------------------------------------------


class _Canvas:
    """A strip drawn in millimetres from its top left corner, as seen from the copper side. 255 = copper."""

    def __init__(self, width_mm: float, height_mm: float, px_mm: float) -> None:
        self.px = px_mm
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.image = Image.new("L", (round(width_mm / px_mm), round(height_mm / px_mm)), 0)
        self.draw = ImageDraw.Draw(self.image)

    def rect(self, x0: float, y0: float, x1: float, y1: float, value: int = 255) -> None:
        p = self.px
        self.draw.rectangle([round(x0 / p), round(y0 / p), round(x1 / p) - 1, round(y1 / p) - 1], fill=value)

    def circle(self, cx: float, cy: float, radius: float, value: int = 255) -> None:
        p = self.px
        self.draw.ellipse([(cx - radius) / p, (cy - radius) / p, (cx + radius) / p, (cy + radius) / p], fill=value)

    def text(self, x: float, y: float, height_mm: float, text: str, value: int = 255, max_width_mm: float = 0) -> float:
        """Write ``text`` with its letters ``height_mm`` high (capital height), the top left corner at (x, y).
        Returns the width in mm. With ``max_width_mm`` the text is made smaller until it fits."""
        size = max(4, round(height_mm / 0.73 / self.px))  # capital letters are about 0.73 of the font size
        font = ImageFont.truetype(str(LABEL_FONT), size)
        if max_width_mm:
            while size > 4 and font.getlength(text) * self.px > max_width_mm:
                size -= 1
                font = ImageFont.truetype(str(LABEL_FONT), size)
        left, top, right, _bottom = font.getbbox(text)
        self.draw.text((x / self.px - left, y / self.px - top), text, fill=value, font=font)
        return (right - left) * self.px


def _line_row(canvas: _Canvas, y: float, width: float) -> None:
    """Tracks of ``width``: a label, four tracks with gaps of the same width, a single track and a slit of that
    width in copper."""
    height, right = LINE_ROW_MM, canvas.width_mm - 0.5
    canvas.text(0.5, y + (height - LABEL_MM) / 2, LABEL_MM, f"{width:g}")
    x = ROW_START_MM
    for _ in range(4):
        canvas.rect(x, y, x + width, y + height)
        x += 2 * width
    x += 1.0 - width
    canvas.rect(x, y, x + width, y + height)
    x += width + 1.0
    block = min(2.2, right - x)
    if block >= 3 * width:
        canvas.rect(x, y, x + block, y + height)
        middle = x + block / 2
        canvas.rect(middle - width / 2, y, middle + width / 2, y + height, 0)


def _smd_row(canvas: _Canvas, y: float, pitch: float, pad_w: float, pad_h: float) -> None:
    canvas.text(0.5, y + (pad_h - LABEL_MM) / 2, LABEL_MM, f"{pitch:g}")
    x = ROW_START_MM
    while x + pad_w <= canvas.width_mm - 0.5:
        canvas.rect(x, y, x + pad_w, y + pad_h)
        x += pitch


def _tht_row(canvas: _Canvas, y: float) -> None:
    """Round pads with drill hole and vias, alternating."""
    x, big = 0.5, True
    while True:
        outer, hole = (1.8, 0.8) if big else (0.8, 0.35)
        if x + outer > canvas.width_mm - 0.5:
            return
        canvas.circle(x + outer / 2, y + 0.9, outer / 2)
        canvas.circle(x + outer / 2, y + 0.9, hole / 2, 0)
        x += outer + 0.6
        big = not big


def _pour(canvas: _Canvas, y: float) -> None:
    """A copper pour with tracks and a pad cut free by isolation gaps of 0.2, 0.3, 0.4 and 0.25 mm."""
    right = canvas.width_mm - 0.5
    canvas.rect(0.5, y, right, y + POUR_MM)
    for row, gap in enumerate((0.2, 0.3, 0.4)):
        top = y + 1.2 + row * 2.4
        canvas.rect(1.2 - gap, top - gap, right - 3.0 + gap, top + 0.3 + gap, 0)
        canvas.rect(1.2, top, right - 3.0, top + 0.3)
    cx, cy = (0.5 + right) / 2, y + 8.8
    canvas.circle(cx, cy, 0.8 + 0.25, 0)
    canvas.circle(cx, cy, 0.8)
    canvas.circle(cx, cy, 0.4, 0)


def _fine_text(canvas: _Canvas, y: float) -> None:
    """Text 1.0, 0.8 and 0.6 mm high, as copper and cut free in copper."""
    fit = canvas.width_mm - 2.0
    canvas.text(0.5, y, 1.0, "PCB 1.0", max_width_mm=fit)
    canvas.text(0.5, y + 1.6, 0.8, "PCB 0.8", max_width_mm=fit)
    canvas.rect(0.5, y + 3.0, canvas.width_mm - 0.5, y + FINE_TEXT_MM)
    canvas.text(1.0, y + 3.4, 0.8, "PCB 0.8", 0, max_width_mm=fit)
    canvas.text(1.0, y + 4.5, 0.6, "PCB 0.6", 0, max_width_mm=fit)


def strip_pattern(width_mm: float, height_mm: float, seconds: int, px_mm: float) -> Image.Image:
    """The exposure of one strip at ``px_mm`` per pixel, as seen from the copper side: 255 = exposed (no copper),
    0 = copper. Rows that do not fit into the height are left out."""
    canvas = _Canvas(width_mm, height_mm, px_mm / SUPERSAMPLE)
    # the total time of the strip, cut free in a copper block
    canvas.rect(0.5, 0.5, width_mm - 0.5, 8.5)
    canvas.text(1.2, 2.3, 4.4, f"{seconds} s", 0, max_width_mm=width_mm - 2.4)
    rows: list[tuple[float, Callable[..., None], tuple[float, ...]]] = [
        (LINE_ROW_MM, _line_row, (w,)) for w in LINE_WIDTHS_MM
    ]
    rows += [(r[2], _smd_row, r) for r in SMD_ROWS_MM]
    rows += [(THT_ROW_MM, _tht_row, ()), (POUR_MM, _pour, ()), (FINE_TEXT_MM, _fine_text, ())]
    y = 10.0
    for height, draw, args in rows:
        if y + height > height_mm - 0.5:
            break
        draw(canvas, y, *args)
        y += height + ROW_GAP_MM
    size = (round(width_mm / px_mm), round(height_mm / px_mm))
    exposed = ImageOps.invert(canvas.image).resize(size, Image.Resampling.BOX)
    return exposed.point(lambda v: 255 if v >= 128 else 0)


def series_layers(
    plan: SeriesPlan, panel_width_mm: float, panel_height_mm: float, printer: PrinterProfile
) -> list[Image.Image]:
    """One display image per exposure: exposure k shows the strips 1 to k, everything else is black."""
    steps = len(plan.section_s)
    pixel = printer.pixel_mm
    width = strip_width_mm(panel_width_mm, steps)
    height = panel_height_mm - 2 * MARGIN_MM
    strips = [ImageOps.mirror(strip_pattern(width, height, seconds, pixel)) for seconds in plan.section_s]
    top = round((printer.display_height_mm - printer.frame_bottom_mm - panel_height_mm + MARGIN_MM) / pixel)
    images: list[Image.Image] = []
    display = Image.new("L", (printer.resolution_x, printer.resolution_y), 0)
    for index, strip in enumerate(strips):
        # strip 1 is the leftmost seen from the copper side, so the rightmost on the display (top view)
        x_copper_side = MARGIN_MM + index * (width + GAP_MM)
        left = round((printer.frame_left_mm + panel_width_mm - x_copper_side - width) / pixel)
        display = display.copy()
        display.paste(strip, (left, top))
        image = ImageOps.mirror(display) if printer.mirror_x else display
        images.append(image.convert("1"))
    return images


def layer_order(plan: SeriesPlan) -> list[int]:
    """Index of the image of every layer: exposure k is ``layers_per_exposure[k]`` layers of image k."""
    return [k for k, count in enumerate(plan.layers_per_exposure) for _ in range(count)]
