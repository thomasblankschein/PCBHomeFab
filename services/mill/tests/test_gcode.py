import json
import math
import re
from dataclasses import replace
from pathlib import Path

import pytest

from mill import gcode
from mill.boards import read_board
from mill.common import Problem
from mill.profiles import MILL_3018PRO, Panel

DATA = Path(__file__).parent / "data"
CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def _placement(board_id: str, x: float, y: float) -> gcode.Placement:
    board = read_board((DATA / f"{board_id}.zip").read_bytes(), board_id)
    return gcode.Placement(
        x, y, board.width_mm, board.height_mm, [(h.x_mm, h.y_mm, h.diameter_mm) for h in board.holes]
    )


def _example_placements() -> list[gcode.Placement]:
    layout = json.loads((CONTRACTS / "examples" / "layout.json").read_text())
    return [_placement(p["board_id"], p["x_mm"], p["y_mm"]) for p in layout["placements"]]


@pytest.fixture(scope="module")
def programs() -> list[gcode.Program]:
    return gcode.generate(_example_placements(), Panel(), MILL_3018PRO)


def _coordinates(code: str, move: str) -> set[tuple[float, float]]:
    pattern = re.compile(rf"^{move} X(-?[\d.]+) Y(-?[\d.]+)", re.M)
    return {(float(x), float(y)) for x, y in pattern.findall(code)}


def test_one_program_per_tool(programs: list[gcode.Program]) -> None:
    assert [p.holes for p in programs] == [100, 52, 2]
    assert programs[2].outlines == 16
    assert [p.filename for p in programs] == ["1_drill_0.8mm.nc", "2_drill_1.0mm.nc", "3_mill_1.0mm.nc"]


def test_drill_positions_match_old_script(programs: list[gcode.Program]) -> None:
    reference = (DATA / "reference_drill_0.8.nc").read_text()
    assert _coordinates(programs[0].code, "G0") - {(0.0, 0.0)} == _coordinates(reference, "G0")


def test_outline_and_hole_circles_match_old_script(programs: list[gcode.Program]) -> None:
    reference = (DATA / "reference_mill_1.0.nc").read_text()
    assert _coordinates(programs[2].code, "G1") == _coordinates(reference, "G1")
    assert _coordinates(programs[2].code, "G3") == _coordinates(reference, "G3")


def test_depths_and_bounds(programs: list[gcode.Program]) -> None:
    for program in programs:
        zs = [float(z) for z in re.findall(r"Z(-?[\d.]+)", program.code)]
        xs = [float(x) for x in re.findall(r" X(-?[\d.]+)", program.code)]
        ys = [float(y) for y in re.findall(r" Y(-?[\d.]+)", program.code)]
        assert min(xs) >= 0 and max(xs) <= Panel().width_mm
        assert min(ys) >= 0 and max(ys) <= Panel().height_mm
        assert max(zs) <= MILL_3018PRO.tool_change_z_mm
    assert min(float(z) for z in re.findall(r"Z(-?[\d.]+)", programs[0].code)) == pytest.approx(-1.75)
    assert min(float(z) for z in re.findall(r"Z(-?[\d.]+)", programs[2].code)) == pytest.approx(-1.75)


def test_programs_are_self_contained(programs: list[gcode.Program]) -> None:
    for program in programs:
        lines = program.code.splitlines()
        assert "M3 S20000" in lines
        assert lines[-4:] == ["G0 Z30.000", "G0 X0.000 Y0.000", "M5", "M30"]  # parked, spindle off


def test_hole_without_drill_or_room_is_rejected() -> None:
    placement = _placement("basisplatine", 3.0, 3.0)
    thin = gcode.Placement(3.0, 3.0, placement.width_mm, placement.height_mm, [(2.0, 2.0, 1.05)])
    with pytest.raises(Problem) as caught:
        gcode.generate([thin], Panel(), MILL_3018PRO)
    assert caught.value.code == "mill.no_drill"


def test_preview_is_svg() -> None:
    svg = gcode.preview_svg([_placement("basisplatine", 3.0, 3.0)], Panel(), MILL_3018PRO)
    assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_tool_change_height_comes_from_the_profile() -> None:
    mill = replace(MILL_3018PRO, tool_change_z_mm=42.0)
    for program in gcode.generate(_example_placements(), Panel(), mill):
        lines = program.code.splitlines()
        assert lines[-4:] == ["G0 Z42.000", "G0 X0.000 Y0.000", "M5", "M30"]
        assert "G0 Z42.000" in lines[:8]


def test_every_program_starts_with_a_tool_change(programs: list[gcode.Program]) -> None:
    for program in programs:
        lines = program.code.splitlines()
        start = lines.index("M5")
        assert lines[start : start + 3] == ["M5", "G0 Z30.000", "G0 X0.000 Y0.000"]
        assert lines[start + 3].startswith("(MSG, Insert the ") and lines[start + 3].endswith(", then resume)")
        assert lines[start + 4] == "M0"  # pause: tool change and Z0, then resume
        assert lines.index("M0") < lines.index("M3 S20000")  # the spindle only starts after the tool change
        assert lines[start + 5] == "G0 Z3"


MARKS_X_FLIP = [(2.0, 98.0), (158.0, 2.0)]  # design view; with flip "x" they lie at the upper right and lower left


def test_lower_left_mark_becomes_the_origin() -> None:
    plain = gcode.generate(_example_placements(), Panel(), MILL_3018PRO)
    mill, second = gcode.origin_of_marks(Panel(), MILL_3018PRO, MARKS_X_FLIP)
    assert second == pytest.approx((156.0, 96.0))
    marked = gcode.generate(_example_placements(), Panel(), mill, second_mark=second)
    for before, after in zip(plain, marked, strict=True):
        moves = (_coordinates(before.code, "G1") | _coordinates(before.code, "G0")) - {
            (0.0, 0.0)
        }  # (0, 0): tool change
        moved = (_coordinates(after.code, "G1") | _coordinates(after.code, "G0")) - {(0.0, 0.0)}
        assert {(round(x - 2.0, 3), round(y - 2.0, 3)) for x, y in moves} == moved


def test_marks_are_named_in_the_headers() -> None:
    mill, second = gcode.origin_of_marks(Panel(), MILL_3018PRO, MARKS_X_FLIP)
    for program in gcode.generate(_example_placements(), Panel(), mill, second_mark=second):
        lines = program.code.splitlines()
        assert "centre of the lower left positioning mark" in lines[1]
        assert lines[2] == "(Second positioning mark, upper right: X156.000 Y96.000)"
    plain = gcode.generate(_example_placements(), Panel(), MILL_3018PRO)
    assert "Second positioning mark" not in plain[0].code


@pytest.mark.parametrize(
    ("flip", "marks"),
    [
        ("x", [(2.0, 98.0), (158.0, 2.0)]),
        ("y", [(2.0, 98.0), (158.0, 2.0)]),
        ("none", [(2.0, 2.0), (158.0, 98.0)]),
    ],
)
def test_the_second_mark_is_always_the_far_corner(flip: str, marks: list[tuple[float, float]]) -> None:
    mill, second = gcode.origin_of_marks(Panel(), replace(MILL_3018PRO, flip=flip), marks)
    assert second == pytest.approx((156.0, 96.0))
    assert gcode.build_layout([], Panel(), mill).holes == {}


def test_marks_on_one_line_are_refused() -> None:
    with pytest.raises(Problem) as caught:
        gcode.origin_of_marks(Panel(), MILL_3018PRO, [(2.0, 2.0), (158.0, 2.0)])
    assert caught.value.code == "mill.invalid_marks"


def test_estimate_seconds_counts_moves_arcs_and_waiting() -> None:
    from mill.gcode import estimate_seconds

    # 60 mm at 60 mm/min, a full circle of radius 10 mm at 120 mm/min, 3 s of waiting; the pause at M0 is free
    code = "G0 X0 Y0\nG4 P3\nG1 X60 Y0 F60\nG3 X60 Y0 I10 J0 F120\nM0\nG0 X60 Y15\n"
    expected = 3 + 60 + (2 * math.pi * 10) / 120 * 60 + 15 / 1500 * 60
    assert estimate_seconds(code) == pytest.approx(expected)
    assert estimate_seconds("(only a comment)\nM5\n") == 0.0
