import io
import json
import zipfile
from pathlib import Path

import pytest

from conftest import validate
from ingest.common import Problem
from ingest.package import MAX_ZIP_FILES, build_package


def _board(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        assert sorted(package.namelist()) == ["board.json", "copper.gbr"]
        board = json.loads(package.read("board.json"))
    validate("board", board)
    return board


def _hole_counts(board: dict) -> dict[float, int]:
    counts: dict[float, int] = {}
    for hole in board["holes"]:
        counts[hole["diameter_mm"]] = counts.get(hole["diameter_mm"], 0) + 1
    return counts


def test_node_size_and_holes(data_dir: Path) -> None:
    board = _board(build_package((data_dir / "fuehlerknoten.zip").read_bytes(), "node"))
    assert (board["width_mm"], board["height_mm"]) == (10.0, 26.0)
    assert _hole_counts(board) == {0.8: 6, 1.0: 2}
    assert all(0 <= h["x_mm"] <= 10 and 0 <= h["y_mm"] <= 26 for h in board["holes"])
    assert board["name"] == "node"


def test_base_board_holes(data_dir: Path) -> None:
    board = _board(build_package((data_dir / "basisplatine.zip").read_bytes(), "base"))
    assert (board["width_mm"], board["height_mm"]) == (28.2, 38.0)
    assert _hole_counts(board) == {0.8: 10, 1.0: 22, 2.2: 2}
    assert [h["plated"] for h in board["holes"] if h["diameter_mm"] == 2.2] == [False, False]


def test_copper_file_is_the_uploaded_file(data_dir: Path) -> None:
    upload = (data_dir / "fuehlerknoten.zip").read_bytes()
    with zipfile.ZipFile(io.BytesIO(build_package(upload, "node"))) as package:
        copper = package.read("copper.gbr")
    with zipfile.ZipFile(io.BytesIO(upload)) as source:
        originals = [source.read(n) for n in source.namelist() if n.endswith("B_Cu.gbr")]
    assert copper in originals


def test_package_is_deterministic(data_dir: Path) -> None:
    upload = (data_dir / "fuehlerknoten.zip").read_bytes()
    assert build_package(upload, "node") == build_package(upload, "node")


def _problem(data: bytes) -> Problem:
    with pytest.raises(Problem) as caught:
        build_package(data, "x")
    return caught.value


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_rejects_non_zip() -> None:
    assert _problem(b"this is not a zip").code == "ingest.invalid_zip"


def test_rejects_zip_without_gerber() -> None:
    assert _problem(_zip({"readme.txt": b"no gerber here"})).code in {"ingest.unreadable_gerber", "ingest.no_copper"}


def test_rejects_too_many_files() -> None:
    assert _problem(_zip({f"f{i}.txt": b"x" for i in range(MAX_ZIP_FILES + 1)})).code == "ingest.too_many_files"


def test_rejects_zip_bomb() -> None:
    bomb = _zip({"big.gbr": b"0" * (60 * 1024 * 1024)})  # compresses to a few KB, 60 MB unpacked
    assert len(bomb) < 200_000
    assert _problem(bomb).code == "ingest.too_large_unpacked"


def test_path_traversal_names_do_not_escape(data_dir: Path, tmp_path: Path) -> None:
    """Names with .. are written inside the temporary folder or ignored; the call must not touch other places."""
    marker = tmp_path / "evil.txt"
    upload = _zip({"../../evil.txt": b"x", "/abs/evil.txt": b"x", "a.gbr": b"G04*\nM02*\n"})
    with pytest.raises(Problem):
        build_package(upload, "x")
    assert not marker.exists()


def test_zip_with_only_the_needed_layers(data_dir: Path) -> None:
    """KiCad export with just B.Cu, Edge.Cuts and the drill files (gerbonara cannot map these on its own)."""
    source = zipfile.ZipFile(data_dir / "fuehlerknoten.zip")
    kept = {
        entry.filename: source.read(entry)
        for entry in source.infolist()
        if entry.filename.endswith(("B_Cu.gbr", "Edge_Cuts.gbr", ".drl"))
    }
    board = _board(build_package(_zip(kept), "node"))
    reference = _board(build_package((data_dir / "fuehlerknoten.zip").read_bytes(), "node"))
    assert (board["width_mm"], board["height_mm"]) == (reference["width_mm"], reference["height_mm"])
    assert len(board["holes"]) == len(reference["holes"])
