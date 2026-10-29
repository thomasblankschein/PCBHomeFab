"""Packing boards onto the panel."""

from __future__ import annotations

from dataclasses import dataclass

from .common import Problem


@dataclass(frozen=True)
class BoardSpec:
    id: str
    width_mm: float
    height_mm: float
    count: int


@dataclass(frozen=True)
class Placement:
    """A board at a position on the panel (lower left corner of the board, panel origin at its lower left)."""

    board_id: str
    x_mm: float
    y_mm: float


def pack(
    boards: list[BoardSpec], panel_width_mm: float, panel_height_mm: float, gap_mm: float, margin_mm: float
) -> list[Placement]:
    """Place boards in rows from the lower left corner, left to right, new rows go up.

    The order of ``boards`` decides the order of placement, each board is repeated ``count`` times.
    """
    placements: list[Placement] = []
    x = y = margin_mm
    row_height = 0.0
    for spec in boards:
        if spec.width_mm > panel_width_mm - 2 * margin_mm:
            raise Problem(422, "panel.board_too_wide", f"Board '{spec.id}' is wider than the panel.")
        for _ in range(spec.count):
            if x + spec.width_mm > panel_width_mm - margin_mm:
                x = margin_mm
                y += row_height + gap_mm
                row_height = 0.0
            if y + spec.height_mm > panel_height_mm - margin_mm:
                raise Problem(
                    422, "panel.does_not_fit", "The boards do not fit on the panel. Reduce the count or the spacing."
                )
            placements.append(Placement(spec.id, round(x, 3), round(y, 3)))
            x += spec.width_mm + gap_mm
            row_height = max(row_height, spec.height_mm)
    return placements
