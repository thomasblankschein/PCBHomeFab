"""Milling the real board contour: offset of the path, tabs, cutouts, direction and the preview."""

import io
import json
import math
import re
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point, Polygon

from conftest import validate
from mill import gcode
from mill.common import Problem
from mill.gcode import Placement, Shape, _area, _sections, tool_paths
from mill.main import Settings, create_app
from mill.profiles import MILL_3018PRO, Panel

DATA = Path(__file__).parent / "data"
R = 0.5  # radius of the 1 mm end mill


def rounded_rectangle(w: float, h: float, r: float, steps: int = 12) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    corners = [(w - r, r, -90), (w - r, h - r, 0), (r, h - r, 90), (r, r, 180)]
    for cx, cy, start in corners:
        for i in range(steps + 1):
            angle = math.radians(start + 90 * i / steps)
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def circle(cx: float, cy: float, r: float, steps: int = 90) -> list[tuple[float, float]]:
    return [
        (cx + r * math.cos(2 * math.pi * i / steps), cy + r * math.sin(2 * math.pi * i / steps)) for i in range(steps)
    ]


def placement(shape: Shape | None, w: float = 20, h: float = 10) -> Placement:
    return Placement(3.0, 3.0, w, h, [], shape)


def test_rectangle_contour_gives_the_same_code_as_no_contour() -> None:
    plain = placement(None, 28.2, 38.0)
    rect = placement(([(0, 0), (28.2, 0), (28.2, 38.0), (0, 38.0)], []), 28.2, 38.0)
    for flip in ("x", "y", "none"):
        mill = replace(MILL_3018PRO, flip=flip)
        a = gcode.generate([plain], Panel(), mill)
        b = gcode.generate([rect], Panel(), mill)
        assert [p.code for p in a] == [p.code for p in b]
        assert gcode.preview_svg([plain], Panel(), mill) == gcode.preview_svg([rect], Panel(), mill)


def test_tool_path_runs_at_the_tool_radius_outside_the_contour() -> None:
    shape: Shape = (rounded_rectangle(20, 10, 2), [])
    [(path, tabs)] = tool_paths(shape, R)
    assert tabs is True and path[0] == path[-1] and _area(path[:-1]) > 0  # closed, counter-clockwise
    board = Polygon(shape[0])
    assert all(abs(board.exterior.distance(Point(p)) - R) < 0.02 for p in path)
    assert Polygon(path).contains(board)


def test_path_starts_at_the_lowest_left_point() -> None:
    [(path, _)] = tool_paths((rounded_rectangle(20, 10, 2), []), R)
    lowest = min(y for _, y in path)
    assert path[0][1] == lowest and path[0][0] == min(x for x, y in path if y == lowest)


def test_rounded_board_has_a_tab_on_every_long_side() -> None:
    [(path, _)] = tool_paths((rounded_rectangle(20, 10, 2), []), R)
    sections = _sections(path, MILL_3018PRO, True)
    tabs = [s for s in sections if s[4]]
    assert len(tabs) == 4
    assert all(abs(math.hypot(s[2] - s[0], s[3] - s[1]) - MILL_3018PRO.tab_width_mm) < 1e-6 for s in tabs)
    assert not any(s[4] for s in _sections(path, MILL_3018PRO, False))
    assert not any(s[4] for s in _sections(path, replace(MILL_3018PRO, tabs=False), True))


def test_round_board_gets_tabs_spread_over_the_circle() -> None:
    [(path, _)] = tool_paths((circle(8, 8, 8), []), R)
    sections = _sections(path, MILL_3018PRO, True)
    tab_length = sum(math.hypot(s[2] - s[0], s[3] - s[1]) for s in sections if s[4])
    assert abs(tab_length - 4 * MILL_3018PRO.tab_width_mm) < 0.05
    # sections join up: every section starts where the previous one ended
    assert all(a[2:4] == b[0:2] for a, b in zip(sections, sections[1:], strict=False))


def test_cutouts_are_milled_first_inside_clockwise_without_tabs() -> None:
    shape: Shape = (rounded_rectangle(30, 20, 2), [circle(15, 10, 3)])
    paths = tool_paths(shape, R)
    assert len(paths) == 2
    (cut, cut_tabs), (outer, outer_tabs) = paths
    assert (cut_tabs, outer_tabs) == (False, True)
    assert _area(cut[:-1]) < 0 and _area(outer[:-1]) > 0  # cutout clockwise, outer counter-clockwise
    cutout = Polygon(shape[1][0])
    assert all(abs(cutout.exterior.distance(Point(p)) - R) < 0.02 for p in cut)
    assert all(cutout.contains(Point(p)) for p in cut)  # the tool stays inside the cutout


def test_cutout_too_small_for_the_tool() -> None:
    with pytest.raises(Problem) as caught:
        tool_paths((rounded_rectangle(30, 20, 2), [circle(15, 10, 0.4)]), R)
    assert caught.value.code == "mill.cutout_too_small"


def test_generate_mills_cutouts_before_the_outer_contour() -> None:
    shape: Shape = (rounded_rectangle(30, 20, 2), [circle(15, 10, 3)])
    programs = gcode.generate([placement(shape, 30, 20)], Panel(), MILL_3018PRO)
    [program] = programs
    assert program.outlines == 1
    moves = re.findall(r"^G1 X(-?[\d.]+) Y(-?[\d.]+) F", program.code, re.M)
    points = [(float(x), float(y)) for x, y in moves]
    # machine coordinates are mirrored in X (flip x): the board spans x 160-33 .. 160-3
    first_inside = [p for p in points if 160 - 18 - 3.5 < p[0] < 160 - 18 + 3.5 and 13 - 3.5 < p[1] < 13 + 3.5]
    assert first_inside and points.index(first_inside[0]) < len(points) // 2


@pytest.mark.parametrize("flip", ["x", "y", "none"])
def test_outer_path_stays_counter_clockwise_when_the_panel_is_turned(flip: str) -> None:
    l_shape = [(0.0, 0.0), (20.0, 0.0), (20.0, 5.0), (5.0, 5.0), (5.0, 15.0), (0.0, 15.0)]
    mill = replace(MILL_3018PRO, flip=flip)
    layout = gcode.build_layout([placement((l_shape, []), 20, 15)], Panel(), mill)
    [(path, _)] = tool_paths(layout.outlines[0], R)
    assert _area(path[:-1]) > 0 and path[0][1] == min(y for _, y in path)


def test_preview_draws_the_real_shape() -> None:
    svg = gcode.preview_svg(
        [placement((rounded_rectangle(30, 20, 2), [circle(15, 10, 3)]), 30, 20)], Panel(), MILL_3018PRO
    )
    assert "<path" in svg and 'fill-rule="evenodd"' in svg and svg.count(" Z") == 2
    rect = gcode.preview_svg([placement(None)], Panel(), MILL_3018PRO)
    assert "<rect" in rect and "<path" not in rect


def test_api_mills_the_contour_of_board_json() -> None:
    package = zipfile.ZipFile(DATA / "basisplatine.zip")
    board = json.loads(package.read("board.json"))
    validate("board", board)
    assert board["contour"]["cutouts"] == [] and len(board["contour"]["outer"]) == 4
    w, h = 24.0, 18.0
    board.update(
        width_mm=w,
        height_mm=h,
        holes=[],
        contour={"outer": rounded_rectangle(w, h, 3), "cutouts": [circle(12, 9, 3)]},
    )
    validate("board", json.loads(json.dumps(board)))
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("board.json", json.dumps(board))
        archive.writestr("copper.gbr", "G04*\nM02*\n")
    layout = {
        "panel": {"width_mm": 160, "height_mm": 100},
        "placements": [{"board_id": "round", "x_mm": 3, "y_mm": 3, "rotation_deg": 0}],
    }
    client = TestClient(create_app(Settings(isolate=False)))
    response = client.post(
        "/v1/programs",
        files=[("packages", ("round.zip", raw.getvalue()))],
        data={"layout": json.dumps(layout), "settings": json.dumps({"mill": "3018pro"})},
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["1_mill_1.0mm.nc", "preview.svg", "programs.json"]
        code = archive.read("1_mill_1.0mm.nc").decode()
        assert b"<path" in archive.read("preview.svg")
    assert code.count("G1 X") > 100  # the arcs are many short moves


def test_every_board_of_a_file_with_several_outlines_is_milled() -> None:
    def box(x: float, w: float) -> list[tuple[float, float]]:
        return [(x, 0.0), (x + w, 0.0), (x + w, 20.0), (x, 20.0)]

    placement = Placement(
        3.0,
        3.0,
        50.0,
        20.0,
        [],
        (box(0, 20), []),
        others=(([(30.0, 0.0), (50.0, 0.0), (50.0, 20.0), (30.0, 20.0)], []),),
    )
    layout = gcode.build_layout([placement], Panel(), MILL_3018PRO)
    assert len(layout.outlines) == 2
    programs = gcode.generate([placement], Panel(), MILL_3018PRO, gcode.load_tools())
    mill = next(p for p in programs if p.tool.startswith("endmill"))
    assert mill.outlines == 2


def test_a_hole_that_is_a_cutout_of_the_outline_is_milled_only_once() -> None:
    outer = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
    contour: Shape = (outer, [circle(10.0, 15.0, 3.6)])
    mounting = (10.0, 15.0, 7.2)  # the same circle as a drilled hole
    other = (30.0, 15.0, 7.2)  # no cutout there: milled as a hole
    both = Placement(3.0, 3.0, 40.0, 30.0, [mounting, other], contour)
    layout = gcode.build_layout([both], Panel(), MILL_3018PRO)
    assert [len(points) for points in layout.holes.values()] == [1]
    only_outline = Placement(3.0, 3.0, 40.0, 30.0, [mounting], contour)
    assert gcode.build_layout([only_outline], Panel(), MILL_3018PRO).holes == {}
    # a hole of the same size somewhere else is not a cutout
    assert gcode.build_layout([replace(only_outline, holes=[(20.0, 15.0, 7.2)])], Panel(), MILL_3018PRO).holes
