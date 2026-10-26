"""The contour from the Edge.Cuts layer: lines, arcs, cutouts, and what happens when the outline is not closed."""

import io
import math
import zipfile
from pathlib import Path

from conftest import validate
from ingest.package import build_package

HEAD = """%TF.FileFunction,Profile,NP*%
%FSLAX46Y46*%
%MOMM*%
%LPD*%
G01*
%ADD10C,0.050000*%
D10*
"""


def _mm(value: float) -> str:
    return f"{round(value * 1e6):d}"


def line(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"X{_mm(x1)}Y{_mm(y1)}D02*\nG01*\nX{_mm(x2)}Y{_mm(y2)}D01*\n"


def arc(x1: float, y1: float, x2: float, y2: float, cx: float, cy: float, counter_clockwise: bool = True) -> str:
    code = "G03" if counter_clockwise else "G02"
    return f"X{_mm(x1)}Y{_mm(y1)}D02*\nG75*\n{code}*\nX{_mm(x2)}Y{_mm(y2)}I{_mm(cx - x1)}J{_mm(cy - y1)}D01*\nG01*\n"


def rounded_rectangle(x0: float, y0: float, w: float, h: float, r: float) -> str:
    return (
        line(x0 + r, y0, x0 + w - r, y0)
        + arc(x0 + w - r, y0, x0 + w, y0 + r, x0 + w - r, y0 + r)
        + line(x0 + w, y0 + r, x0 + w, y0 + h - r)
        + arc(x0 + w, y0 + h - r, x0 + w - r, y0 + h, x0 + w - r, y0 + h - r)
        + line(x0 + w - r, y0 + h, x0 + r, y0 + h)
        + arc(x0 + r, y0 + h, x0, y0 + h - r, x0 + r, y0 + h - r)
        + line(x0, y0 + h - r, x0, y0 + r)
        + arc(x0, y0 + r, x0 + r, y0, x0 + r, y0 + r)
    )


def circle(cx: float, cy: float, r: float) -> str:
    return arc(cx + r, cy, cx + r, cy, cx, cy)


def board_with_outline(data_dir: Path, outline: str) -> bytes:
    """The node board with another Edge.Cuts layer."""
    source = zipfile.ZipFile(data_dir / "fuehlerknoten.zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for entry in source.infolist():
            content = source.read(entry)
            if entry.filename.endswith("Edge_Cuts.gbr"):
                content = (HEAD + outline + "M02*\n").encode()
            archive.writestr(entry.filename, content)
    return buffer.getvalue()


def _board(upload: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(build_package(upload, "x"))) as package:
        import json

        board = json.loads(package.read("board.json"))
    validate("board", board)
    return board


def area(polygon: list[list[float]]) -> float:
    pairs = zip(polygon, polygon[1:] + polygon[:1], strict=True)
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in pairs)) / 2


def test_rectangle_board_has_a_four_point_contour(data_dir: Path) -> None:
    board = _board((data_dir / "fuehlerknoten.zip").read_bytes())
    assert sorted(map(tuple, board["contour"]["outer"])) == [(0.0, 0.0), (0.0, 26.0), (10.0, 0.0), (10.0, 26.0)]
    assert board["contour"]["cutouts"] == []


def test_rounded_corners_follow_the_arcs(data_dir: Path) -> None:
    board = _board(board_with_outline(data_dir, rounded_rectangle(10, -20, 20, 10, 2)))
    assert (board["width_mm"], board["height_mm"]) == (20.0, 10.0)
    outer = board["contour"]["outer"]
    assert len(outer) > 30
    assert all(0 <= x <= 20.0001 and 0 <= y <= 10.0001 for x, y in outer)
    assert abs(area(outer) - (200 - (4 - math.pi) * 4)) < 0.05
    assert [0.0, 2.0] in outer and [2.0, 0.0] in outer  # the ends of the corner arc
    assert [0.0, 0.0] not in outer  # the sharp corner is gone


def test_cutouts_are_separate_polygons(data_dir: Path) -> None:
    outline = rounded_rectangle(10, -20, 20, 10, 2) + circle(20, -15, 1.5)
    board = _board(board_with_outline(data_dir, outline))
    assert len(board["contour"]["cutouts"]) == 1
    assert abs(area(board["contour"]["cutouts"][0]) - math.pi * 1.5**2) < 0.05
    assert abs(area(board["contour"]["outer"]) - (200 - (4 - math.pi) * 4)) < 0.05


def test_round_board_gets_its_size_from_the_circle(data_dir: Path) -> None:
    board = _board(board_with_outline(data_dir, circle(30, -30, 8)))
    assert (board["width_mm"], board["height_mm"]) == (16.0, 16.0)
    assert abs(area(board["contour"]["outer"]) - math.pi * 64) < 0.2


def test_segments_in_any_order_and_direction_are_joined(data_dir: Path) -> None:
    outline = line(20, -10, 10, -10) + line(10, -20, 20, -20) + line(10, -10, 10, -20) + line(20, -20, 20, -10)
    board = _board(board_with_outline(data_dir, outline))
    assert sorted(map(tuple, board["contour"]["outer"])) == [(0.0, 0.0), (0.0, 10.0), (10.0, 0.0), (10.0, 10.0)]


def test_open_outline_falls_back_to_the_box(data_dir: Path) -> None:
    outline = line(10, -20, 20, -20) + line(20, -20, 20, -10) + line(20, -10, 10, -10)  # left side missing
    board = _board(board_with_outline(data_dir, outline))
    assert "contour" not in board
    assert (board["width_mm"], board["height_mm"]) == (10.0, 10.0)
