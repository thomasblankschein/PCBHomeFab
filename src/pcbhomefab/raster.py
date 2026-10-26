"""Rasterizing the bottom copper layer.

The result is the board in top view (as KiCad draws it), one pixel per ``px_mm``. 255 = copper, 0 = no copper.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageDraw

from .board import Board

Point = tuple[float, float]


def _draw_line(draw: ImageDraw.ImageDraw, p1: Point, p2: Point, width_px: float, value: int) -> None:
    """Straight line with round caps."""
    radius = max(width_px / 2, 0.5)
    for cx, cy in (p1, p2):
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=value)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return
    nx, ny = -dy / length * radius, dx / length * radius
    draw.polygon(
        [
            (p1[0] + nx, p1[1] + ny),
            (p2[0] + nx, p2[1] + ny),
            (p2[0] - nx, p2[1] - ny),
            (p1[0] - nx, p1[1] - ny),
        ],
        fill=value,
    )


def _draw_primitive(draw: ImageDraw.ImageDraw, prim: Any, to_px: Callable[[float, float], Point], scale: float) -> None:
    value = 255 if prim.polarity_dark else 0
    kind = type(prim).__name__
    if kind == "Circle":
        cx, cy = to_px(prim.x, prim.y)
        r = prim.r * scale
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=value)
    elif kind == "Line":
        _draw_line(draw, to_px(prim.x1, prim.y1), to_px(prim.x2, prim.y2), prim.width * scale, value)
    elif kind in ("Rectangle", "Arc", "ArcPoly"):
        poly = prim if kind == "ArcPoly" else prim.to_arc_poly()
        outline = poly.approximate_arcs().outline
        if len(outline) >= 3:
            draw.polygon([to_px(x, y) for x, y in outline], fill=value)
    else:
        raise ValueError(f"Unsupported Gerber primitive: {kind}")


def rasterize_copper(board: Board, px_mm: float = 0.04, supersample: int = 4) -> Image.Image:
    """Draw the bottom copper in top view. Returns a mode ``L`` image, 255 = copper, thresholded at 50 %."""
    width = round(board.width_mm / px_mm)
    height = round(board.height_mm / px_mm)
    scale = supersample / px_mm  # pixels per mm in the supersampled image

    def to_px(x: float, y: float) -> Point:
        return (x - board.xmin) * scale, (board.ymax - y) * scale

    big = Image.new("L", (width * supersample, height * supersample), 0)
    draw = ImageDraw.Draw(big)
    for obj in board.copper.objects:
        for prim in obj.to_primitives("mm"):
            _draw_primitive(draw, prim, to_px, scale)
    coverage = big.resize((width, height), Image.Resampling.BOX)
    return coverage.point(lambda v: 255 if v >= 128 else 0)
