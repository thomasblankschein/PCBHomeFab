"""Reading a ``.kicad_pcb`` file directly. The reference is the Gerber ZIP exported from the same board."""

from __future__ import annotations

import io
import json
import math
import zipfile
from pathlib import Path

import pytest

from conftest import validate
from ingest.common import Problem
from ingest.package import build_package


def _unpack(data: bytes) -> tuple[dict, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        assert sorted(package.namelist()) == ["board.json", "copper.gbr"]
        board = json.loads(package.read("board.json"))
        copper = package.read("copper.gbr").decode()
    validate("board", board)
    return board, copper


def _holes(board: dict) -> list[tuple[float, float, float, bool]]:
    return sorted((round(h["x_mm"], 2), round(h["y_mm"], 2), h["diameter_mm"], h["plated"]) for h in board["holes"])


def test_kicad_file_gives_the_same_board_as_the_gerber_export(data_dir: Path) -> None:
    from_kicad, copper = _unpack(build_package((data_dir / "fuehlerknoten.kicad_pcb").read_bytes(), "node"))
    from_gerber, _ = _unpack(build_package((data_dir / "fuehlerknoten.zip").read_bytes(), "node"))
    assert from_kicad["outline"] == from_gerber["outline"]
    assert (from_kicad["width_mm"], from_kicad["height_mm"]) == (10.0, 26.0)
    assert _holes(from_kicad) == _holes(from_gerber)
    assert from_kicad["contour"] == from_gerber["contour"]
    assert copper.startswith("G04 PCBHomeFab") and copper.rstrip().endswith("M02*")
    assert "G36*" in copper  # the copper pour


def test_package_is_deterministic(data_dir: Path) -> None:
    data = (data_dir / "fuehlerknoten.kicad_pcb").read_bytes()
    assert build_package(data, "node") == build_package(data, "node")


def _pcb(body: str, outline: str = "") -> bytes:
    edge = (
        outline
        or """
      (gr_line (start 0 0) (end 20 0) (layer "Edge.Cuts") (width 0.1))
      (gr_line (start 20 0) (end 20 10) (layer "Edge.Cuts") (width 0.1))
      (gr_line (start 20 10) (end 0 10) (layer "Edge.Cuts") (width 0.1))
      (gr_line (start 0 10) (end 0 0) (layer "Edge.Cuts") (width 0.1))"""
    )
    return f'(kicad_pcb (version 20260206) (generator "pcbnew") {edge} {body})'.encode()


TRACK = '(segment (start 2 2) (end 8 2) (width 0.5) (layer "B.Cu") (net 1))'


def test_tracks_pads_vias_and_holes() -> None:
    body = f"""{TRACK}
      (via (at 10 5) (size 1.2) (drill 0.6) (layers "F.Cu" "B.Cu") (net 1))
      (footprint "X" (layer "F.Cu") (at 15 5 90)
        (pad "1" thru_hole oval (at 0 0 90) (size 2 1) (drill 0.8) (layers "*.Cu" "*.Mask"))
        (pad "2" np_thru_hole circle (at 0 3) (size 1.5 1.5) (drill 1.5) (layers "*.Cu" "*.Mask"))
        (pad "3" smd rect (at 0 -3) (size 1 1) (layers "F.Cu")))"""
    board, copper = _unpack(build_package(_pcb(body), "t"))
    assert (board["width_mm"], board["height_mm"]) == (20.0, 10.0)
    assert board["outline"] == {
        "xmin": 0.0,
        "ymin": -10.0,
        "xmax": 20.0,
        "ymax": 0.0,
    }  # Y is up, like in the Gerber files
    # the via at (10, 5), the pad at (15, 5) and the mounting hole 3 mm "below" it in the footprint, which is turned
    # by 90 degrees: it ends up 3 mm to the right
    assert _holes(board) == [(10.0, 5.0, 0.6, True), (15.0, 5.0, 0.8, True), (18.0, 5.0, 1.5, False)]
    assert "D01*" in copper and "D03*" in copper
    # the mounting hole has no ring and the F.Cu pad is not on the bottom layer: one oval stroke, one via flash
    assert copper.count("D03*") == 1


def test_footprint_rotation_turns_the_pads() -> None:
    body = """(footprint "X" (layer "F.Cu") (at 10 5 90)
        (pad "1" thru_hole circle (at 2 0 90) (size 1.5 1.5) (drill 0.8) (layers "*.Cu")))"""
    board, _ = _unpack(build_package(_pcb(body), "t"))
    # 2 mm to the right of the footprint, turned counterclockwise by 90 degrees on screen: 2 mm up (KiCad Y down)
    assert _holes(board) == [(10.0, 7.0, 0.8, True)]


def test_circle_outline_gives_a_round_contour() -> None:
    circle = '(gr_circle (center 10 10) (end 15 10) (layer "Edge.Cuts") (width 0.1) (fill no))'
    board, _ = _unpack(build_package(_pcb(f"{TRACK}", circle), "t"))
    assert (board["width_mm"], board["height_mm"]) == (10.0, 10.0)
    outer = board["contour"]["outer"]
    assert len(outer) > 16
    assert all(abs(math.hypot(x - 5, y - 5) - 5) < 0.01 for x, y in outer)


def test_arc_corner_follows_the_arc() -> None:
    outline = """
      (gr_line (start 0 0) (end 8 0) (layer "Edge.Cuts") (width 0.1))
      (gr_arc (start 8 0) (mid 10.828427 1.171573) (end 12 4) (layer "Edge.Cuts") (width 0.1))
      (gr_line (start 12 4) (end 12 10) (layer "Edge.Cuts") (width 0.1))
      (gr_line (start 12 10) (end 0 10) (layer "Edge.Cuts") (width 0.1))
      (gr_line (start 0 10) (end 0 0) (layer "Edge.Cuts") (width 0.1))"""
    board, _ = _unpack(build_package(_pcb(TRACK, outline), "t"))
    assert len(board["contour"]["outer"]) > 8
    assert (board["width_mm"], board["height_mm"]) == (12.0, 10.0)


def test_filled_zone_becomes_a_region() -> None:
    zone = """(zone (net 1) (layer "B.Cu") (fill yes (thermal_gap 0.5))
        (polygon (pts (xy 1 1) (xy 19 1) (xy 19 9) (xy 1 9)))
        (filled_polygon (layer "B.Cu") (pts (xy 1 1) (xy 19 1) (xy 19 9) (xy 1 9))))"""
    _, copper = _unpack(build_package(_pcb(zone), "t"))
    assert copper.count("G36*") == 1 and copper.count("G37*") == 1


def test_unfilled_zone_is_refused_but_a_zone_outline_is_not() -> None:
    unfilled = '(zone (net 1) (layer "B.Cu") (fill yes) (polygon (pts (xy 1 1) (xy 19 1) (xy 19 9))))'
    with pytest.raises(Problem) as error:
        build_package(_pcb(f"{TRACK} {unfilled}"), "t")
    assert error.value.code == "ingest.zone_not_filled"
    outline_only = '(zone (net 1) (layer "B.Cu") (polygon (pts (xy 1 1) (xy 19 1) (xy 19 9))))'
    _unpack(build_package(_pcb(f"{TRACK} {outline_only}"), "t"))
    on_front = '(zone (net 1) (layer "F.Cu") (fill yes) (polygon (pts (xy 1 1) (xy 19 1) (xy 19 9))))'
    _unpack(build_package(_pcb(f"{TRACK} {on_front}"), "t"))


def test_text_on_the_bottom_copper_is_drawn_mirrored_when_asked() -> None:
    def strokes(justify: str) -> list[float]:
        font = "(font (size 2 2) (thickness 0.3))"
        text = f'(gr_text "H" (at 10 5) (layer "B.Cu") (effects {font} (justify left {justify})))'
        _, copper = _unpack(build_package(_pcb(text), "t"))
        return [int(line.split("X")[1].split("Y")[0]) / 1e6 for line in copper.splitlines() if line.startswith("X")]

    normal, mirrored = strokes(""), strokes("mirror")
    assert normal and min(normal) >= 10 - 1e-6 and max(normal) <= 12.5
    assert max(mirrored) <= 10 + 1e-6 and min(mirrored) >= 7.5


def test_front_text_and_front_graphics_are_ignored() -> None:
    text = '(gr_text "H" (at 10 5) (layer "F.SilkS") (effects (font (size 2 2) (thickness 0.3))))'
    with pytest.raises(Problem) as error:
        build_package(_pcb(text), "t")
    assert error.value.code == "ingest.no_copper"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            '(footprint "X" (at 5 5) (pad "1" smd trapezoid (at 0 0) (size 1 1) (layers "B.Cu")))',
            "ingest.unsupported_kicad",
        ),
        (
            '(footprint "X" (at 5 5) (pad "1" thru_hole oval (at 0 0) (size 2 1) (drill oval 1 0.6) (layers "*.Cu")))',
            "ingest.slots_unsupported",
        ),
        ('(gr_curve (pts (xy 0 0) (xy 1 1) (xy 2 1) (xy 3 0)) (layer "B.Cu") (width 0.2))', "ingest.unsupported_kicad"),
    ],
)
def test_unsupported_things_are_refused(body: str, code: str) -> None:
    with pytest.raises(Problem) as error:
        build_package(_pcb(f"{TRACK} {body}"), "t")
    assert error.value.code == code


def test_board_without_copper_or_outline() -> None:
    with pytest.raises(Problem) as error:
        build_package(_pcb(""), "t")
    assert error.value.code == "ingest.no_copper"
    with pytest.raises(Problem) as error:
        build_package(b"(kicad_pcb " + TRACK.encode() + b")", "t")
    assert error.value.code == "ingest.no_outline"


def test_broken_kicad_file() -> None:
    for data in (b"(kicad_pcb (segment", b"(kicad_pcb))((", b"(kicad_sch (version 1))", b"(kicad_pcb \xff)"):
        with pytest.raises(Problem) as error:
            build_package(data, "t")
        assert error.value.code in {"ingest.invalid_kicad", "ingest.invalid_zip"}


def test_kicad_file_with_three_boards_keeps_every_outline() -> None:
    def box(x: float, w: float) -> str:
        return f'(gr_rect (start {x} 0) (end {x + w} 10) (layer "Edge.Cuts") (width 0.1) (fill no))'

    board, _ = _unpack(build_package(_pcb(TRACK, box(0, 20) + box(25, 15) + box(45, 10)), "t"))
    assert (board["width_mm"], board["height_mm"]) == (55.0, 10.0)
    assert len(board["contour"]["others"]) == 2
