"""Panelizing: packing boards onto the blank."""

from __future__ import annotations

from dataclasses import dataclass

from .board import Board
from .errors import LayoutError
from .profiles import Plate


@dataclass(frozen=True)
class Placement:
    """A board at a position on the plate (lower left corner of the board, plate origin at its lower left)."""

    board: Board
    x_mm: float
    y_mm: float

    @property
    def x1_mm(self) -> float:
        return self.x_mm + self.board.width_mm

    @property
    def y1_mm(self) -> float:
        return self.y_mm + self.board.height_mm


def pack(boards: list[Board], plate: Plate, gap_mm: float = 3.0, margin_mm: float = 3.0) -> list[Placement]:
    """Place boards in rows from the lower left corner, left to right, new rows go up.

    The order of ``boards`` decides the order of placement. Raises ``LayoutError`` if they do not fit.
    """
    placements: list[Placement] = []
    x = y = margin_mm
    row_height = 0.0
    for board in boards:
        if board.width_mm > plate.width_mm - 2 * margin_mm:
            raise LayoutError(f"Board '{board.name}' is wider than the plate.")
        if x + board.width_mm > plate.width_mm - margin_mm:
            x = margin_mm
            y += row_height + gap_mm
            row_height = 0.0
        if y + board.height_mm > plate.height_mm - margin_mm:
            raise LayoutError("The boards do not fit on the plate. Reduce the count or the spacing.")
        placements.append(Placement(board, round(x, 3), round(y, 3)))
        x += board.width_mm + gap_mm
        row_height = max(row_height, board.height_mm)
    return placements
