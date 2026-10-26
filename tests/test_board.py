from pathlib import Path

import pytest

from pcbhomefab.board import load_board
from pcbhomefab.errors import InputError

DATA = Path(__file__).parent / "data"


def test_node_size_and_holes() -> None:
    board = load_board(DATA / "fuehlerknoten.zip")
    assert (board.width_mm, board.height_mm) == (10.0, 26.0)
    assert board.hole_diameters() == {0.8: 6, 1.0: 2}
    assert all(0 <= h.x <= 10 and 0 <= h.y <= 26 for h in board.holes)


def test_base_board_holes() -> None:
    board = load_board(DATA / "basisplatine.zip")
    assert (board.width_mm, board.height_mm) == (28.2, 38.0)
    assert board.hole_diameters() == {0.8: 10, 1.0: 22, 2.2: 2}
    assert [h.plated for h in board.holes if h.diameter == 2.2] == [False, False]


def test_rejects_non_zip() -> None:
    with pytest.raises(InputError):
        load_board(b"this is not a zip")


def test_rejects_zip_without_copper() -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "no gerber here")
    with pytest.raises(InputError):
        load_board(buffer.getvalue())
