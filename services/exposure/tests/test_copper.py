"""The copper picture of the 3D view: smooth edges, drill holes open."""

from pathlib import Path

import pytest

from exposure.boards import Board, Placement, load_board
from exposure.mask import COPPER_PX_MM, build_copper

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def node() -> Board:
    return load_board((DATA / "fuehlerknoten.zip").read_bytes(), "fuehlerknoten")


def test_copper_picture_has_smooth_edges_and_open_holes(node: Board) -> None:
    picture = build_copper([Placement(node, 5.0, 5.0)], 40.0, 40.0)
    assert picture.size == (round(40.0 / COPPER_PX_MM), round(40.0 / COPPER_PX_MM))
    alpha = picture.getchannel("A")
    values = set(alpha.getdata())
    assert 0 in values and 255 in values
    assert any(0 < v < 255 for v in values)  # anti-aliased edges, not only on / off
    hole = node.holes[0]
    x = round((5.0 + hole.x) / COPPER_PX_MM)
    y = round((40.0 - 5.0 - hole.y) / COPPER_PX_MM)
    assert alpha.getpixel((x, y)) == 0  # the drill hole is open
