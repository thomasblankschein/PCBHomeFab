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


def alignment_marks(width_mm: float, height_mm: float, flip: str) -> dict[str, Any]:
    """The two marks (centres in plate coordinates, design view) for a plate, and where the second one is in G-code.

    ``flip`` is how the plate is turned over for milling: ``x`` mirrors X, ``y`` mirrors Y, ``none`` leaves it. The mark
    pattern is chosen so that it looks the same on the mill whatever the way the plate is turned.
    """
    a = INSET_MM
    if flip == "none":
        points = [(a, a), (width_mm - a, height_mm - a)]
        voids = "tl-br"
    else:
        # lower left and upper right of the plate after turning it over
        points = [(a, height_mm - a), (width_mm - a, a)]
        voids = "tr-bl"
    return {
        "points": [{"x_mm": x, "y_mm": y, "voids": voids} for x, y in points],
        #: The plate's lower left corner in the G-code coordinates, which have the lower left mark as origin.
        "plate_origin_mm": {"x_mm": -a, "y_mm": -a},
        "second_mm": {"x_mm": width_mm - 2 * a, "y_mm": height_mm - 2 * a},
    }
