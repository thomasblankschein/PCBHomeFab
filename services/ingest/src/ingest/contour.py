"""The real board contour from the Edge.Cuts layer: closed loops of lines and arcs as polygons.

The result goes to ``board.json`` as ``contour`` (``contracts/schemas/board.schema.json``). A file can hold several
boards, each with its own outline: every loop that does not lie inside another one is the outer contour of a board
("shape"), loops inside it are its cutouts. When the layer cannot be read as closed loops, ``extract_contour`` returns
``None`` and the board is treated as its bounding box.
"""

from __future__ import annotations

from typing import Any

#: Largest distance between the real arc and its polygon, in mm.
MAX_ARC_ERROR_MM = 0.005
#: Two segment ends closer than this belong together, in mm.
JOIN_TOLERANCE_MM = 0.005
MAX_SEGMENTS = 5000
MAX_POINTS = 20000

Point = tuple[float, float]
#: The outer polygon of one board and the polygons of its cutouts.
Shape = tuple[list[Point], list[list[Point]]]


def _polyline(obj: Any) -> list[Point] | None:
    """A line or an arc as a list of points, ``None`` for anything else (regions, flashes, ...)."""
    kind = type(obj).__name__
    obj = obj.converted("mm")
    if kind == "Line":
        return [(obj.x1, obj.y1), (obj.x2, obj.y2)]
    if kind == "Arc":
        pieces = obj.approximate(max_error=MAX_ARC_ERROR_MM)
        points = [(obj.x1, obj.y1)]
        points += [(piece.x2, piece.y2) for piece in pieces[:-1]]
        points.append((obj.x2, obj.y2))
        return points
    return None


def _close(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) <= JOIN_TOLERANCE_MM and abs(a[1] - b[1]) <= JOIN_TOLERANCE_MM


def _chain(segments: list[list[Point]]) -> list[list[Point]] | None:
    """Join the segments end to end into loops. ``None`` when a loop does not close."""
    remaining = [list(s) for s in segments if len(s) >= 2 and not (len(s) == 2 and _close(s[0], s[1]))]
    loops: list[list[Point]] = []
    while remaining:
        path = remaining.pop(0)
        while not _close(path[0], path[-1]):
            for index, segment in enumerate(remaining):
                if _close(path[-1], segment[0]):
                    path += segment[1:]
                elif _close(path[-1], segment[-1]):
                    path += segment[-2::-1]
                else:
                    continue
                del remaining[index]
                break
            else:
                return None
        loops.append(path[:-1])
    return loops


def _area(loop: list[Point]) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1], strict=True)) / 2


def _inside(point: Point, loop: list[Point]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def relative(loop: list[Point], xmin: float, ymin: float) -> list[list[float]]:
    """Points relative to the lower left corner of the outline box, without repeated points."""
    cleaned: list[list[float]] = []
    for x, y in loop:
        point = [round(x - xmin, 4), round(y - ymin, 4)]
        if not cleaned or point != cleaned[-1]:
            cleaned.append(point)
    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    return cleaned


def extract_contour(outline: Any) -> list[Shape] | None:
    """The boards of the outline layer as shapes (largest first), points in mm in the coordinates of the Gerber file.

    Returns ``None`` when the outline is not made of closed loops of lines and arcs, or when it is too large; the board
    is then milled as its bounding box.
    """
    segments: list[list[Point]] = []
    for obj in outline.objects:
        polyline = _polyline(obj)
        if polyline is None:
            return None
        segments.append(polyline)
    return contour_of(segments)


def contour_of(segments: list[list[Point]]) -> list[Shape] | None:
    """Like :func:`extract_contour` for an outline that is already a list of polylines (lines and arcs as points)."""
    if not segments or len(segments) > MAX_SEGMENTS:
        return None
    loops = _chain(segments)
    if not loops or sum(len(loop) for loop in loops) > MAX_POINTS:
        return None
    loops = [loop for loop in loops if len(loop) >= 3 and abs(_area(loop)) > 1e-6]
    if not loops:
        return None
    loops.sort(key=lambda loop: abs(_area(loop)), reverse=True)
    # a loop inside an odd number of larger loops is a cutout of the smallest one around it, the others are boards
    shapes: list[Shape] = []
    owners: dict[int, int] = {}  # index of a board loop -> index in shapes
    for index, loop in enumerate(loops):
        around = [j for j in range(index) if _inside(loop[0], loops[j])]
        if len(around) % 2 == 0:
            owners[index] = len(shapes)
            shapes.append((loop, []))
        else:
            owner = around[-1]
            if owner not in owners:
                return None  # a cutout inside a cutout: not a shape this service understands
            shapes[owners[owner]][1].append(loop)
    return shapes
