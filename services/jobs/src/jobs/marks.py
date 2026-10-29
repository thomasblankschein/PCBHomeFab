"""Positioning marks: two marks on the copper layer that show where the plate lies on the mill.

They stand diagonally opposite in the margin of the plate. After the plate is turned over for milling one of them is at
the lower left (it becomes X0 Y0 of the G-code) and the other one at the upper right, so the second mark always has
the same coordinates relative to the first, whatever the way the plate is turned. The ``exposure`` service draws the
marks (about 3.4 mm square with their free ring), the ``mill`` service uses them as the origin.
"""

from __future__ import annotations

from typing import Any

#: Distance of the centre of a mark from the nearest plate edges.
INSET_MM = 2.0
#: A mark with its free ring spans 3.4 mm: from 0.3 to 3.7 mm from the edges. Boards need 0.5 mm for the outline mill
#: cut and some room beyond that.
MIN_MARGIN_MM = 4.5
MIN_PLATE_MM = 20.0
#: The origin mark stands diagonally outside the corner of the area of the boards: this far from it in X and in Y. Its
#: free ring (radius 1.7 mm) then keeps 1.1 mm from the corner, enough for the outline mill cut.
NEAR_BOARDS_MM = 2.0

Box = tuple[float, float, float, float]


def alignment_marks(
    width_mm: float, height_mm: float, flip: str, labels: bool = False, boards: Box | None = None
) -> dict[str, Any]:
    """The two marks (centres in plate coordinates, design view) for a plate, and where the second one is in G-code.

    ``flip`` is how the plate is turned over for milling: ``x`` mirrors X, ``y`` mirrors Y, ``none`` leaves it. The mark
    pattern is chosen so that it looks the same on the mill whatever the way the plate is turned. With ``labels`` every
    mark gets its G-code coordinates as text, mirrored like the plate is turned over.

    The mark that is the origin of the G-code (X0 Y0, at the lower left after turning the plate) stands in the corner
    of the plate. With ``boards`` (``xmin, ymin, xmax, ymax`` of everything that is placed on the plate) it stands as
    close as possible to the boards instead; the other mark stays in the opposite corner.
    """
    a = INSET_MM
    far_x, far_y = width_mm - a, height_mm - a
    near = NEAR_BOARDS_MM
    if flip == "none":
        origin = (a, a) if boards is None else (boards[0] - near, boards[1] - near)
        second = (far_x, far_y)
        voids = "tl-br"
    elif flip == "x":
        origin = (far_x, a) if boards is None else (boards[2] + near, boards[1] - near)
        second = (a, far_y)
        voids = "tr-bl"
    else:
        origin = (a, far_y) if boards is None else (boards[0] - near, boards[3] + near)
        second = (far_x, a)
        voids = "tr-bl"
    origin = (min(max(origin[0], a), far_x), min(max(origin[1], a), far_y))
    points = [second, origin] if flip == "x" else [origin, second]

    def machine(point: tuple[float, float]) -> tuple[float, float]:
        """Plate coordinates of the design view to coordinates on the mill (the plate lower left is 0, 0)."""
        x, y = point
        return (width_mm - x if flip == "x" else x, height_mm - y if flip == "y" else y)

    origin_on_mill, second_on_mill = machine(origin), machine(second)
    delta = {
        "x_mm": round(second_on_mill[0] - origin_on_mill[0], 4),
        "y_mm": round(second_on_mill[1] - origin_on_mill[1], 4),
    }
    points_json: list[dict[str, Any]] = [{"x_mm": round(x, 4), "y_mm": round(y, 4), "voids": voids} for x, y in points]
    if labels:
        for point_json, point in zip(points_json, points, strict=True):
            is_origin = point == origin
            point_json["label"] = "X0 Y0" if is_origin else f"X{delta['x_mm']:g} Y{delta['y_mm']:g}"
            point_json["label_flip"] = flip
            point_json["label_side"] = "right" if point[0] < width_mm / 2 else "left"
    return {
        "points": points_json,
        #: The plate's lower left corner in the G-code coordinates, which have the origin mark as zero.
        "plate_origin_mm": {"x_mm": round(-origin_on_mill[0], 4), "y_mm": round(-origin_on_mill[1], 4)},
        "second_mm": delta,
    }
