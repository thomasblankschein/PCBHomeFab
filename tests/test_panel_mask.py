from pathlib import Path

import pytest
from PIL import Image, ImageChops

from pcbhomefab.board import Board, load_board
from pcbhomefab.errors import LayoutError
from pcbhomefab.mask import build_mask
from pcbhomefab.panel import pack
from pcbhomefab.profiles import PHOTON_M3, Plate

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def base() -> Board:
    return load_board(DATA / "basisplatine.zip")


@pytest.fixture(scope="module")
def node() -> Board:
    return load_board(DATA / "fuehlerknoten.zip")


def test_pack_positions(base: Board, node: Board) -> None:
    placements = pack([base] + [node] * 15, Plate())
    positions = [(p.x_mm, p.y_mm) for p in placements]
    assert positions[0] == (3.0, 3.0)
    assert positions[1:10] == [(34.2 + 13 * i, 3.0) for i in range(9)]
    assert positions[10:] == [(3.0 + 13 * i, 44.0) for i in range(6)]


def test_pack_rejects_too_many(node: Board) -> None:
    with pytest.raises(LayoutError):
        pack([node] * 100, Plate())


def test_mask_polarity_copper_is_black(base: Board) -> None:
    """The base board has a GND pour: most of it is copper, so most of the mask must be black."""
    mask = build_mask(pack([base], Plate()), PHOTON_M3)
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
    outside = mask.crop((0, 0, 400, 400)).convert("L")
    assert max(outside.tobytes()) == 0


def test_mask_is_one_bit_at_display_size(base: Board) -> None:
    mask = build_mask(pack([base], Plate()), PHOTON_M3)
    assert mask.mode == "1"
    assert mask.size == (4096, 2560)


def test_mask_matches_reference_from_old_scripts(base: Board, node: Board) -> None:
    """The mask of the old KiCad-SVG based script is the reference. Small edge differences are expected."""
    mask = build_mask(pack([base] + [node] * 15, Plate()), PHOTON_M3, holes="full")
    reference = Image.open(DATA / "reference_mask_fbh.png").convert("L")
    diff = ImageChops.difference(mask.convert("L"), reference)
    different = sum(1 for v in diff.tobytes() if v)
    assert different / (4096 * 2560) < 0.006


def test_hole_modes_change_mask(base: Board) -> None:
    placements = pack([base], Plate())
    full = build_mask(placements, PHOTON_M3, holes="full")
    none = build_mask(placements, PHOTON_M3, holes="none")
    assert full.tobytes() != none.tobytes()
    with pytest.raises(ValueError):
        build_mask(placements, PHOTON_M3, holes="bogus")
