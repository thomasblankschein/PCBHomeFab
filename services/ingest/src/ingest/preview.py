"""Simple copper geometry for the layout preview of the frontend (``copper`` in ``board.json``)."""

from __future__ import annotations

import math
from typing import Any

#: A board with more drawing elements than this gets no copper preview (the board itself is still processed).
MAX_ELEMENTS = 40000
#: Longest straight piece an arc is cut into, in mm.
ARC_STEP_MM = 0.2

Point = tuple[float, float]


def _arc_points(start: Point, end: Point, centre: Point, clockwise: bool) -> list[Point]:
    """Points along an arc from ``start`` to ``end`` around ``centre``, both ends included."""
    radius = math.dist(start, centre)
    first = math.atan2(start[1] - centre[1], start[0] - centre[0])
    last = math.atan2(end[1] - centre[1], end[0] - centre[0])
    sweep = (first - last) % math.tau if clockwise else (last - first) % math.tau
    if math.dist(start, end) < 1e-6:
        sweep = math.tau
    steps = max(2, min(96, math.ceil(sweep * radius / ARC_STEP_MM)))
    sign = -1 if clockwise else 1
    angles = [first + sign * sweep * i / steps for i in range(steps + 1)]
    points = [(centre[0] + radius * math.cos(a), centre[1] + radius * math.sin(a)) for a in angles]
    points[0], points[-1] = start, end
    return points


def _outline_points(primitive: Any) -> list[Point]:
    """The corner points of a filled shape, arcs cut into short pieces."""
    points: list[Point] = []
    for start, end, (clockwise, centre) in primitive.segments:
        piece = [start, end] if clockwise is None else _arc_points(start, end, centre, clockwise)
        points += piece[:-1]
    return points


def copper_preview(layer: Any, xmin: float, ymin: float) -> dict[str, Any] | None:
    """Tracks, round pads and filled shapes of a copper layer, in mm relative to the lower left corner of the outline.

    ``strokes`` are ``[x1, y1, x2, y2, width]`` (round ends), ``discs`` are ``[x, y, diameter]``, ``polygons`` are
    lists of ``[x, y]``. Light (clear) polarity objects are left out. Returns ``None`` when there is too much to draw.
    """
    from gerbonara import graphic_primitives as gp

    def rel(x: float, y: float) -> list[float]:
        return [round(x - xmin, 2), round(y - ymin, 2)]

    strokes: list[list[float]] = []
    discs: list[list[float]] = []
    polygons: list[list[list[float]]] = []
    for obj in layer.objects:
        for primitive in obj.to_primitives("mm"):
            if not primitive.polarity_dark:
                continue
            if isinstance(primitive, gp.Line):
                width = round(primitive.width, 3)
                strokes.append([*rel(primitive.x1, primitive.y1), *rel(primitive.x2, primitive.y2), width])
            elif isinstance(primitive, gp.Arc):
                start, end = (primitive.x1, primitive.y1), (primitive.x2, primitive.y2)
                centre = (primitive.cx, primitive.cy)
                points = _arc_points(start, end, centre, primitive.clockwise)
                for (ax, ay), (bx, by) in zip(points, points[1:], strict=False):
                    strokes.append([*rel(ax, ay), *rel(bx, by), round(primitive.width, 3)])
            elif isinstance(primitive, gp.Circle):
                discs.append([*rel(primitive.x, primitive.y), round(2 * primitive.r, 3)])
            elif isinstance(primitive, gp.Rectangle):
                polygons.append([rel(*p) for p in primitive.to_arc_poly().outline])
            elif isinstance(primitive, gp.ArcPoly):
                polygons.append([rel(*p) for p in _outline_points(primitive)])
        if len(strokes) + len(discs) + len(polygons) > MAX_ELEMENTS:
            return None
    return {"strokes": strokes, "discs": discs, "polygons": polygons}
