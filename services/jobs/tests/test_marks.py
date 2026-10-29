"""Where the positioning marks stand: the origin mark as close to the boards as possible."""

from jobs.marks import alignment_marks

BOARDS = (10.0, 20.0, 60.0, 70.0)  # the area of the boards on a 160 x 100 mm plate


def _origin(marks: dict, flip: str) -> tuple[float, float]:
    point = marks["points"][1 if flip == "x" else 0]
    return point["x_mm"], point["y_mm"]


def test_without_boards_the_marks_stand_in_the_corners() -> None:
    assert _origin(alignment_marks(160, 100, "none"), "none") == (2.0, 2.0)
    assert _origin(alignment_marks(160, 100, "x"), "x") == (158.0, 2.0)
    assert _origin(alignment_marks(160, 100, "y"), "y") == (2.0, 98.0)


def test_origin_mark_stands_diagonally_outside_the_corner_of_the_boards() -> None:
    # lower left of the boards when the plate is not turned, lower right for flip x (X is mirrored), upper left for
    # flip y
    assert _origin(alignment_marks(160, 100, "none", boards=BOARDS), "none") == (8.0, 18.0)
    assert _origin(alignment_marks(160, 100, "x", boards=BOARDS), "x") == (62.0, 18.0)
    assert _origin(alignment_marks(160, 100, "y", boards=BOARDS), "y") == (8.0, 72.0)


def test_other_mark_stays_in_the_opposite_corner_and_is_named_relative_to_the_origin() -> None:
    marks = alignment_marks(160, 100, "none", labels=True, boards=BOARDS)
    assert [(p["x_mm"], p["y_mm"]) for p in marks["points"]] == [(8.0, 18.0), (158.0, 98.0)]
    assert marks["second_mm"] == {"x_mm": 150.0, "y_mm": 80.0}
    assert marks["plate_origin_mm"] == {"x_mm": -8.0, "y_mm": -18.0}
    assert [p["label"] for p in marks["points"]] == ["X0 Y0", "X150 Y80"]
    flipped = alignment_marks(160, 100, "x", boards=BOARDS)
    # the plate is turned in X: the origin mark is at 160 - 62 = 98 from the left edge of the mill, the other at 158
    assert flipped["second_mm"] == {"x_mm": 60.0, "y_mm": 80.0}
    assert flipped["plate_origin_mm"] == {"x_mm": -98.0, "y_mm": -18.0}


def test_the_mark_never_leaves_the_plate() -> None:
    boards = (0.0, 0.0, 160.0, 100.0)  # boards all the way to the edge: no room, the mark stays inside the plate
    assert _origin(alignment_marks(160, 100, "none", boards=boards), "none") == (2.0, 2.0)
    assert _origin(alignment_marks(160, 100, "x", boards=boards), "x") == (158.0, 2.0)
