from pathlib import Path

import pytest

from jobs.plates import PlatesError, load_plates, parse_plates


def test_the_packaged_list_has_the_three_sizes() -> None:
    library = load_plates()
    assert library.source == "built-in"
    assert [(p.id, p.width_mm, p.height_mm, p.name) for p in library.active] == [
        ("160x100", 160.0, 100.0, "160 × 100 mm"),
        ("75x100", 75.0, 100.0, "75 × 100 mm"),
        ("100x75", 100.0, 75.0, "100 × 75 mm"),
    ]


def test_a_user_file_replaces_the_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / "plates.toml"
    file.write_text('[[plate]]\nid = "a"\nname = "Small"\nwidth_mm = 50\nheight_mm = 40.5\n', encoding="utf-8")
    monkeypatch.setenv("PCBHOMEFAB_PLATES_FILE", str(file))
    library = load_plates()
    assert library.source == str(file)
    assert library.to_dict()["plates"] == [{"id": "a", "name": "Small", "width_mm": 50.0, "height_mm": 40.5}]


def test_disabled_plates_are_not_offered() -> None:
    library = parse_plates(
        '[[plate]]\nid = "a"\nwidth_mm = 1\nheight_mm = 1\nenabled = false\n'
        '[[plate]]\nid = "b"\nwidth_mm = 2\nheight_mm = 2\n'
    )
    assert [p.id for p in library.active] == ["b"]
    assert library.find("a") is None and library.find("b") is not None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not toml [",
        '[[plate]]\nid = "a"\nwidth_mm = 0\nheight_mm = 5\n',
        '[[plate]]\nid = "a"\nwidth_mm = "5"\nheight_mm = 5\n',
        '[[plate]]\nid = "a b"\nwidth_mm = 5\nheight_mm = 5\n',
        '[[plate]]\nid = "a"\nwidth_mm = 5\nheight_mm = 5\n[[plate]]\nid = "a"\nwidth_mm = 6\nheight_mm = 6\n',
        '[[plate]]\nid = "a"\nwidth_mm = 5\nheight_mm = 5\ncolour = "red"\n',
        '[[plate]]\nid = "a"\nwidth_mm = 5\nheight_mm = 5\nenabled = false\n',
    ],
)
def test_wrong_lists_are_refused(text: str) -> None:
    with pytest.raises(PlatesError):
        parse_plates(text)


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PlatesError):
        load_plates(tmp_path / "missing.toml")
