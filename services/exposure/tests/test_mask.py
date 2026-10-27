import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageOps

from exposure.boards import Board, Placement, load_board
from exposure.mask import build_mask
from exposure.profiles import PHOTON_M3

DATA = Path(__file__).parent / "data"
LAYOUT = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "examples" / "layout.json").read_text())


@pytest.fixture(scope="module")
def base() -> Board:
    return load_board((DATA / "basisplatine.zip").read_bytes(), "basisplatine")


@pytest.fixture(scope="module")
def node() -> Board:
    return load_board((DATA / "fuehlerknoten.zip").read_bytes(), "fuehlerknoten")


def _one(base: Board) -> list[Placement]:
    return [Placement(base, 3.0, 3.0)]


def test_mask_polarity_copper_is_black(base: Board) -> None:
    """The base board has a GND pour: most of it is copper, so most of the mask must be black."""
    mask = build_mask(_one(base), PHOTON_M3)
    pixel = PHOTON_M3.pixel_mm
    # mirrored in X: the board's plate x range [3, 31.2] maps to display x = width - (frame + x)
    x1 = PHOTON_M3.display_width_mm - (PHOTON_M3.frame_left_mm + 3.0 + base.width_mm)
    x2 = PHOTON_M3.display_width_mm - (PHOTON_M3.frame_left_mm + 3.0)
    y2 = PHOTON_M3.display_height_mm - (PHOTON_M3.frame_bottom_mm + 3.0)
    y1 = y2 - base.height_mm
    area = mask.crop((round(x1 / pixel), round(y1 / pixel), round(x2 / pixel), round(y2 / pixel))).convert("L")
    white = sum(1 for v in area.tobytes() if v) / (area.width * area.height)
    assert white < 0.3
    # outside the boards everything stays dark
    outside = mask.crop((100, 100, 400, 400)).convert("L")
    assert max(outside.tobytes()) == 0


def test_mask_is_one_bit_at_display_size(base: Board) -> None:
    mask = build_mask(_one(base), PHOTON_M3)
    assert mask.mode == "1"
    assert mask.size == (4096, 2560)


def test_mask_matches_reference_from_old_scripts(base: Board, node: Board) -> None:
    """The mask of the old KiCad-SVG based script is the reference. Small edge differences are expected."""
    boards = {"basisplatine": base, "fuehlerknoten": node}
    placements = [Placement(boards[p["board_id"]], p["x_mm"], p["y_mm"]) for p in LAYOUT["placements"]]
    mask = build_mask(placements, PHOTON_M3, holes="full")
    reference = Image.open(DATA / "reference_mask_fbh.png").convert("L")
    diff = ImageChops.difference(mask.convert("L"), reference)
    different = sum(1 for v in diff.tobytes() if v)
    assert different / (4096 * 2560) < 0.006


def test_hole_modes_change_mask(base: Board) -> None:
    full = build_mask(_one(base), PHOTON_M3, holes="full")
    none = build_mask(_one(base), PHOTON_M3, holes="none")
    assert full.tobytes() != none.tobytes()
    with pytest.raises(ValueError):
        build_mask(_one(base), PHOTON_M3, holes="bogus")


def _mark_mask(voids: str, base: Board) -> tuple[Image.Image, float, float]:
    """A mask with a single mark on an empty plate (no boards), and the pixel position of its centre."""
    from exposure.boards import Mark

    mark = Mark(20.0, 30.0, voids)
    mask = build_mask([], replace(PHOTON_M3, mirror_x=False), marks=[mark])
    cx = (PHOTON_M3.frame_left_mm + mark.x_mm) / PHOTON_M3.pixel_mm
    cy = (PHOTON_M3.display_height_mm - PHOTON_M3.frame_bottom_mm - mark.y_mm) / PHOTON_M3.pixel_mm
    return mask.convert("L"), cx, cy


def test_mark_has_copper_pad_free_quadrants_and_free_ring(base: Board) -> None:
    mask, cx, cy = _mark_mask("tl-br", base)
    x, y = round(cx), round(cy)
    d = 15  # pixels from the centre, well inside a quadrant (a quadrant is about 26 px)
    assert mask.getpixel((x - d, y - d)) == 255 and mask.getpixel((x + d, y + d)) == 255  # free quadrants
    assert mask.getpixel((x + d, y - d)) == 0 and mask.getpixel((x - d, y + d)) == 0  # copper quadrants
    ring = round((2.4 / 2 + 0.25) / PHOTON_M3.pixel_mm)  # in the free ring around the pad
    assert mask.getpixel((x + ring, y)) == 255 and mask.getpixel((x, y - ring)) == 255
    far = round(2.4 / PHOTON_M3.pixel_mm)  # outside the ring the plate is copper
    assert mask.getpixel((x + far, y)) == 0 and mask.getpixel((x, y + far)) == 0


def test_other_mark_pattern_swaps_the_quadrants(base: Board) -> None:
    mask, cx, cy = _mark_mask("tr-bl", base)
    x, y = round(cx), round(cy)
    assert mask.getpixel((x + 15, y - 15)) == 255 and mask.getpixel((x - 15, y + 15)) == 255
    assert mask.getpixel((x - 15, y - 15)) == 0 and mask.getpixel((x + 15, y + 15)) == 0


def test_mark_centre_stays_where_it_is_when_too_much_is_etched(base: Board) -> None:
    """Both free squares touch at the centre. Etching a little too much grows them equally, so the middle of the part
    where they overlap is still the centre."""
    from PIL import ImageFilter

    mask, cx, cy = _mark_mask("tl-br", base)
    grown = mask.filter(ImageFilter.MaxFilter(7))  # every free area grows by 3 pixels all around
    x, y = round(cx), round(cy)
    box = grown.crop((x - 12, y - 12, x + 12, y + 12))
    # the copper quadrants shrink, the centre of the remaining copper cross sections stays on the mark centre
    xs, ys = [], []
    for py in range(24):
        for px in range(24):
            if box.getpixel((px, py)) == 255 and mask.crop((x - 12, y - 12, x + 12, y + 12)).getpixel((px, py)) == 0:
                xs.append(px)
                ys.append(py)
    # the area that was copper and is now free lies symmetric around the centre (12, 12) of the crop
    assert abs(sum(xs) / len(xs) - 11.5) < 1.0 and abs(sum(ys) / len(ys) - 11.5) < 1.0


def test_mark_is_mirrored_with_the_display() -> None:
    from exposure.boards import Mark

    mark = Mark(20.0, 30.0, "tl-br")
    plain = build_mask([], replace(PHOTON_M3, mirror_x=False), marks=[mark])
    mirrored = build_mask([], replace(PHOTON_M3, mirror_x=True), marks=[mark])
    assert ImageOps.mirror(plain.convert("L")).tobytes() == mirrored.convert("L").tobytes()


def test_no_marks_no_change(base: Board) -> None:
    assert build_mask(_one(base), PHOTON_M3).tobytes() == build_mask(_one(base), PHOTON_M3, marks=None).tobytes()
