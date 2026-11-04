import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import CONTRACTS, validate
from exposure import pm3
from exposure.main import Settings, create_app
from exposure.profiles import PHOTON_M3
from exposure.series import (
    GAP_MM,
    MARGIN_MM,
    SeriesError,
    check_strips,
    layer_order,
    plan_series,
    series_layers,
    strip_pattern,
    strip_width_mm,
)

REQUEST = json.loads((CONTRACTS / "examples" / "exposure-series-request.json").read_text())
EXPECTED = json.loads((CONTRACTS / "examples" / "exposure-series.json").read_text())


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(Settings(isolate=False)))


def _problem(response: Any, code: str) -> None:
    assert response.status_code == 422
    validate("problem", response.json())
    assert response.json()["code"] == code


def test_plan_of_the_example() -> None:
    validate("exposure-series-request", REQUEST)
    validate("exposure-series", EXPECTED)
    assert plan_series(60, 180, 5, PHOTON_M3).to_dict() == EXPECTED


@pytest.mark.parametrize(
    ("shortest", "longest", "steps"), [(60, 180, 7), (50, 180, 4), (1, 200, 2), (10, 19, 10), (33, 97, 3)]
)
def test_every_strip_gets_its_time(shortest: int, longest: int, steps: int) -> None:
    plan = plan_series(shortest, longest, steps, PHOTON_M3)
    assert plan.section_s[0] == longest and plan.section_s[-1] == shortest
    # exposure k lights the strips 1 to k: strip i gets the exposures i to the last one
    for i, total in enumerate(plan.section_s):
        assert sum(plan.exposure_s[i:]) == total
    assert all(d % plan.unit_s == 0 for d in plan.exposure_s)
    assert plan.layers == longest // plan.unit_s == len(layer_order(plan))


def test_times_are_rounded_half_up() -> None:
    # 100 - 0, 100 - 12.5, 100 - 25, 100 - 37.5, 100 - 50
    assert plan_series(50, 100, 5, PHOTON_M3).section_s == [100, 87, 75, 62, 50]


def test_print_time_counts_the_lift_moves() -> None:
    plan = plan_series(60, 180, 5, PHOTON_M3)
    assert plan.print_time_s == round(6 * (30 + 6 / 3 + 6 / 4))


@pytest.mark.parametrize(
    ("shortest", "longest", "steps", "code"),
    [
        (60, 60, 2, "exposure.invalid_series"),
        (90, 60, 2, "exposure.invalid_series"),
        (60, 64, 6, "exposure.invalid_series"),
        (50, 251, 4, "exposure.series_too_many_layers"),
    ],
)
def test_unusable_values_are_refused(shortest: int, longest: int, steps: int, code: str) -> None:
    with pytest.raises(SeriesError) as error:
        plan_series(shortest, longest, steps, PHOTON_M3)
    assert error.value.code == code


def test_strips_must_be_wide_enough() -> None:
    check_strips(160, 10)
    with pytest.raises(SeriesError, match="at most 4 steps"):
        check_strips(75, 5)


def _lit_strips(image: Image.Image, steps: int, mirrored: bool = False) -> list[bool]:
    """Which strips (1 first, seen from the copper side) have exposed pixels in the display image."""
    printer = PHOTON_M3
    width = strip_width_mm(160, steps)
    lit = []
    grey = image.convert("L")
    for index in range(steps):
        x_copper_side = MARGIN_MM + index * (width + GAP_MM)
        left = printer.frame_left_mm + 160 - x_copper_side - width
        if mirrored:
            left = printer.display_width_mm - left - width
        box = (round(left / printer.pixel_mm) + 5, 0, round((left + width) / printer.pixel_mm) - 5, 2560)
        lit.append(grey.crop(box).getextrema()[1] == 255)
    return lit


def test_exposure_k_lights_the_strips_1_to_k() -> None:
    plan = plan_series(60, 180, 5, PHOTON_M3)
    images = series_layers(plan, 160, 100, PHOTON_M3)
    assert len(images) == 5
    for k, image in enumerate(images, start=1):
        assert image.mode == "1" and image.size == (4096, 2560)
        assert _lit_strips(image, 5) == [i < k for i in range(5)]


def test_mirror_x_puts_strip_1_on_the_other_side() -> None:
    printer = replace(PHOTON_M3, mirror_x=True)
    plan = plan_series(60, 180, 5, printer)
    first = series_layers(plan, 160, 100, printer)[0]
    assert _lit_strips(first, 5, mirrored=True) == [True, False, False, False, False]


def test_border_and_gaps_stay_copper() -> None:
    """Black (no light) outside the strips: the copper of the border and between the strips stays."""
    plan = plan_series(60, 180, 5, PHOTON_M3)
    last = series_layers(plan, 160, 100, PHOTON_M3)[-1].convert("L")
    pixel = PHOTON_M3.pixel_mm
    panel_left = round(PHOTON_M3.frame_left_mm / pixel)
    panel_top = round((PHOTON_M3.display_height_mm - PHOTON_M3.frame_bottom_mm - 100) / pixel)
    margin = round(MARGIN_MM / pixel)
    assert last.crop((panel_left, panel_top, panel_left + 4000 - 100, panel_top + margin - 2)).getextrema() == (0, 0)
    assert last.crop((0, 0, panel_left - 1, 2560)).getextrema() == (0, 0)


def test_pattern_has_copper_and_exposed_areas_and_the_label_block_stays_copper() -> None:
    strip = strip_pattern(20, 94, 120, PHOTON_M3.pixel_mm)
    assert strip.size == (500, 2350)
    low, high = strip.getextrema()
    assert (low, high) == (0, 255)
    # the block with the time is copper (black) with the letters cut free: mostly black
    block = strip.crop((round(0.6 / 0.04), round(0.6 / 0.04), round(19.4 / 0.04), round(2.2 / 0.04)))
    assert block.getextrema() == (0, 0)


def test_pm3_has_one_layer_per_unit_of_time(tmp_path: Path) -> None:
    plan = plan_series(60, 180, 5, PHOTON_M3)
    images = series_layers(plan, 160, 100, PHOTON_M3)
    target = tmp_path / "series.pm3"
    target.write_bytes(pm3.build_pm3_sequence(images, layer_order(plan), PHOTON_M3, plan.unit_s))
    info = pm3.read_pm3(target)
    assert info.machine_name == "Anycubic Photon M3" and info.layer_count == 6 and info.exposure_s == 30
    layers = pm3.read_layers(target)
    assert [seconds for seconds, _ in layers] == [30.0] * 6
    expected = [images[k].convert("L").tobytes() for k in (0, 1, 2, 3, 4, 4)]
    assert [image.tobytes() for _, image in layers] == expected


def test_pm3_sequence_checks_its_input() -> None:
    image = Image.new("1", (4096, 2560))
    with pytest.raises(pm3.Pm3Error):
        pm3.build_pm3_sequence([image], [0, 1], PHOTON_M3, 10)
    with pytest.raises(pm3.Pm3Error):
        pm3.build_pm3_sequence([Image.new("1", (10, 10))], [0], PHOTON_M3, 10)


def test_api_gives_the_three_files(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/v1/exposure-series", json=REQUEST)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["series.json", "series.pm3", "series_preview.png"]
        series = json.loads(archive.read("series.json"))
        (tmp_path / "series.pm3").write_bytes(archive.read("series.pm3"))
        preview = Image.open(io.BytesIO(archive.read("series_preview.png")))
    validate("exposure-series", series)
    assert series == EXPECTED
    assert preview.size == (1024, 640)
    assert pm3.read_pm3(tmp_path / "series.pm3").layer_count == 6
    assert client.post("/v1/exposure-series", json=REQUEST).content == response.content


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"longest_s": 60}, "exposure.invalid_series"),
        ({"shortest_s": 50, "longest_s": 251, "steps": 4}, "exposure.series_too_many_layers"),
        ({"panel": {"width_mm": 75, "height_mm": 100}, "steps": 5}, "exposure.invalid_series"),
        ({"panel": {"width_mm": 170, "height_mm": 100}}, "exposure.panel_too_large"),
        ({"printer": "nope"}, "exposure.unknown_printer"),
        ({"steps": 11}, "common.invalid_request"),
    ],
)
def test_api_refuses_unusable_requests(client: TestClient, change: dict[str, Any], code: str) -> None:
    _problem(client.post("/v1/exposure-series", json={**REQUEST, **change}), code)
