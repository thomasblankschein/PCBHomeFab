from dataclasses import replace
from pathlib import Path

import pytest

from mill import gcode
from mill.common import Problem
from mill.profiles import MILL_3018PRO, Plate
from mill.tools import load_tools, parse_tools

MINIMAL = """
[defaults.drill]
spindle_rpm = 12000
plunge_feed = 80
peck_mm = 0.5
[[tool]]
id = "d1"
kind = "drill"
diameter_mm = 0.8
[[tool]]
id = "e1"
kind = "endmill"
diameter_mm = 1.0
spindle_rpm = 15000
feed = 120
plunge_feed = 30
step_down_mm = 0.3
"""


def _with_holes(*diameters: float) -> list[gcode.Placement]:
    return [gcode.Placement(3.0, 3.0, 28.2, 38.0, [(2.0 + 3.0 * i, 3.0, d) for i, d in enumerate(diameters)])]


def test_default_library_has_drills_and_endmills() -> None:
    library = load_tools()
    assert [t.diameter_mm for t in library.drills()] == [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
    assert [t.diameter_mm for t in library.endmills()] == [1.0, 2.0]
    assert library.endmill(2.0).feed == 180 and library.endmill(1.0).feed == 150  # per tool and from defaults


def test_defaults_are_inherited_and_tools_can_be_disabled() -> None:
    library = parse_tools(MINIMAL)
    assert library.tools[0].spindle_rpm == 12000 and library.tools[0].peck_mm == 0.5
    assert library.tools[1].spindle_rpm == 15000
    off = parse_tools(MINIMAL.replace('id = "d1"', 'id = "d1"\nenabled = false'))
    assert off.drills() == []


@pytest.mark.parametrize(
    "broken",
    [
        "not toml [",
        "",
        MINIMAL.replace('kind = "drill"', 'kind = "laser"'),
        MINIMAL.replace('id = "e1"', 'id = "d1"'),
        MINIMAL.replace("feed = 120", "feed = -1"),
        MINIMAL.replace("feed = 120", 'feed = "fast"'),
        MINIMAL.replace("step_down_mm = 0.3\n", ""),
        MINIMAL.replace("diameter_mm = 0.8", "diameter_mm = 0.8\nstep_down_mm = 1"),
    ],
)
def test_invalid_libraries_are_rejected(broken: str) -> None:
    with pytest.raises(Problem) as caught:
        parse_tools(broken)
    assert caught.value.code == "mill.invalid_tools"


def test_environment_variable_selects_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / "tools.toml"
    file.write_text(MINIMAL, encoding="utf-8")
    monkeypatch.setenv("PCBHOMEFAB_TOOLS_FILE", str(file))
    assert [t.id for t in load_tools().tools] == ["d1", "e1"]
    monkeypatch.setenv("PCBHOMEFAB_TOOLS_FILE", str(tmp_path / "missing.toml"))
    with pytest.raises(Problem) as caught:
        load_tools()
    assert caught.value.code == "mill.invalid_tools"


def test_every_hole_size_gets_its_own_tool() -> None:
    programs = gcode.generate(_with_holes(0.6, 0.9, 1.1, 1.2, 1.3, 7.2), Plate(), MILL_3018PRO, load_tools())
    assert [p.tool for p in programs] == ["drill-0.6", "drill-0.9", "drill-1.1", "drill-1.2", "endmill-1.0"]
    assert [p.holes for p in programs] == [1, 1, 1, 1, 2]  # 1.3 and 7.2 mm are milled
    assert "M3 S20000" in programs[0].code


def test_cutting_data_comes_from_the_tool() -> None:
    library = parse_tools(MINIMAL)
    mill = replace(MILL_3018PRO, max_spindle_rpm=15000)
    drill, cutter = gcode.generate(_with_holes(0.8, 1.5), Plate(), mill, library)
    assert "M3 S12000" in drill.code and "F80" in drill.code
    assert "M3 S15000" in cutter.code and "F120" in cutter.code and "F30" in cutter.code


def test_larger_outline_endmill_and_fallback_for_small_holes() -> None:
    mill = replace(MILL_3018PRO, outline_endmill_mm=2.0)
    programs = gcode.generate(_with_holes(1.3, 5.0), Plate(), mill, load_tools())
    assert [p.tool for p in programs] == ["endmill-2.0", "endmill-1.0"]
    outline = programs[0]
    assert outline.outlines == 1 and outline.holes == 1  # 5 mm circled with the 2 mm mill
    assert programs[1].holes == 1 and programs[1].outlines == 0  # 1.3 mm needs the 1 mm mill


def test_spindle_speed_above_machine_limit_is_refused() -> None:
    slow = replace(MILL_3018PRO, max_spindle_rpm=10000)
    with pytest.raises(Problem, match="rpm") as caught:
        gcode.generate(_with_holes(0.8), Plate(), slow, load_tools())
    assert caught.value.code == "mill.spindle_too_fast"


def test_hole_between_drill_sizes_is_refused_with_a_hint() -> None:
    with pytest.raises(Problem, match="No drill for a 0.95 mm hole") as caught:
        gcode.generate(_with_holes(0.95), Plate(), MILL_3018PRO, load_tools())
    assert caught.value.code == "mill.no_drill"
