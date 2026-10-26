import json
import re
from pathlib import Path

import pytest

from mill import gcode
from mill.boards import read_board
from mill.common import Problem
from mill.profiles import MILL_3018PRO, Plate

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
    return gcode.generate(_example_placements(), Plate(), MILL_3018PRO)


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
        assert min(xs) >= 0 and max(xs) <= Plate().width_mm
        assert min(ys) >= 0 and max(ys) <= Plate().height_mm
        assert max(zs) <= 18.0
    assert min(float(z) for z in re.findall(r"Z(-?[\d.]+)", programs[0].code)) == pytest.approx(-1.9)
    assert min(float(z) for z in re.findall(r"Z(-?[\d.]+)", programs[2].code)) == pytest.approx(-1.65)


def test_programs_are_self_contained(programs: list[gcode.Program]) -> None:
    for program in programs:
        lines = program.code.splitlines()
        assert "M3 S20000" in lines
        assert lines[-2:] == ["M5", "M30"]


def test_hole_without_drill_or_room_is_rejected() -> None:
    placement = _placement("basisplatine", 3.0, 3.0)
    thin = gcode.Placement(3.0, 3.0, placement.width_mm, placement.height_mm, [(2.0, 2.0, 1.05)])
    with pytest.raises(Problem) as caught:
        gcode.generate([thin], Plate(), MILL_3018PRO)
    assert caught.value.code == "mill.no_drill"


def test_preview_is_svg() -> None:
    svg = gcode.preview_svg([_placement("basisplatine", 3.0, 3.0)], Plate(), MILL_3018PRO)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
