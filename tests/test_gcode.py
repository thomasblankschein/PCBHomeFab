import re
from pathlib import Path

import pytest

from pcbhomefab import gcode
from pcbhomefab.board import Board, load_board
from pcbhomefab.errors import LayoutError
from pcbhomefab.panel import pack
from pcbhomefab.profiles import MILL_3018PRO, Plate

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def programs() -> list[gcode.Program]:
    base = load_board(DATA / "basisplatine.zip")
    node = load_board(DATA / "fuehlerknoten.zip")
    placements = pack([base] + [node] * 15, Plate())
    return gcode.generate(placements, Plate(), MILL_3018PRO)


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


def test_hole_without_drill_or_room_is_rejected(programs: list[gcode.Program]) -> None:
    base = load_board(DATA / "basisplatine.zip")
    thin = base.__class__(**{**base.__dict__})
    thin.holes = [h.__class__(h.x, h.y, 1.05, h.plated) for h in base.holes[:1]]
    assert isinstance(thin, Board)
    with pytest.raises(LayoutError):
        gcode.generate(pack([thin], Plate()), Plate(), MILL_3018PRO)


def test_preview_is_svg(programs: list[gcode.Program]) -> None:
    base = load_board(DATA / "basisplatine.zip")
    svg = gcode.preview_svg(pack([base], Plate()), Plate(), MILL_3018PRO)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
