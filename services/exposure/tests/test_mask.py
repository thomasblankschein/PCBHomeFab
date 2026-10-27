import json
from pathlib import Path

import pytest
from PIL import Image, ImageChops

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
