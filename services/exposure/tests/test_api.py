import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import CONTRACTS, contract_operations, validate
from exposure import pm3
from exposure.main import Settings, create_app

DATA = Path(__file__).parent / "data"
LAYOUT = json.loads((CONTRACTS / "examples" / "layout.json").read_text())
SETTINGS = json.loads((CONTRACTS / "examples" / "exposure-settings.json").read_text())


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(Settings(isolate=False)))


def _files() -> list[tuple[str, tuple[str, bytes]]]:
    return [("packages", (f"{n}.zip", (DATA / f"{n}.zip").read_bytes())) for n in ("basisplatine", "fuehlerknoten")]


def _post(client: TestClient, layout: Any = LAYOUT, settings: Any = SETTINGS, files: Any = None) -> Any:
    return client.post(
        "/v1/masks",
        files=_files() if files is None else files,
        data={"layout": json.dumps(layout), "settings": json.dumps(settings)},
    )


def _problem(response: Any, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    validate("problem", response.json())
    assert response.json()["code"] == code


@pytest.fixture(scope="module")
def result(client: TestClient) -> bytes:
    response = _post(client)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    return bytes(response.content)


def test_routes_match_the_contract(client: TestClient) -> None:
    implemented = {
        (method, route.path)
        for route in client.app.routes  # type: ignore[attr-defined]
        for method in getattr(route, "methods", None) or ()
    }
    assert contract_operations() <= implemented


def test_example_request_gives_the_three_files(result: bytes, tmp_path: Path) -> None:
    validate("layout", LAYOUT)
    validate("exposure-settings", SETTINGS)
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert sorted(archive.namelist()) == ["exposure.pm3", "mask.png", "mask_preview.png"]
        mask = Image.open(io.BytesIO(archive.read("mask.png")))
        preview = Image.open(io.BytesIO(archive.read("mask_preview.png")))
        (tmp_path / "exposure.pm3").write_bytes(archive.read("exposure.pm3"))
    assert mask.mode == "1" and mask.size == (4096, 2560)
    assert preview.size == (1024, 640)
    info = pm3.read_pm3(tmp_path / "exposure.pm3")
    assert info.machine_name == "Anycubic Photon M3" and info.exposure_s == 60.0
    assert info.first_layer.tobytes() == mask.convert("L").tobytes()


def test_response_is_deterministic(client: TestClient, result: bytes) -> None:
    assert _post(client).content == result


def test_outputs_can_be_chosen(client: TestClient) -> None:
    response = _post(client, settings={"printer": "photon-m3", "outputs": ["pm3"]})
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["exposure.pm3"]


def test_copper_picture_for_the_3d_view(client: TestClient) -> None:
    response = _post(client, settings={"printer": "photon-m3", "outputs": ["copper"]})
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["copper.png"]
        picture = Image.open(io.BytesIO(archive.read("copper.png")))
    assert picture.mode == "RGBA" and picture.size == (1600, 1000)  # 160 x 100 mm at 10 px/mm
    alpha = picture.getchannel("A")
    assert alpha.getextrema() == (0, 255)
    copper = sum(1 for v in alpha.tobytes() if v)
    assert 0.01 < copper / (1600 * 1000) < 0.5  # some copper, far from everything
    # the corner of the plate has no board and no copper
    assert picture.getpixel((1599, 0))[3] == 0


def test_profiles(client: TestClient) -> None:
    printers = client.get("/v1/profiles").json()["printers"]
    assert printers["photon-m3"]["resolution"] == [4096, 2560]
    assert printers["photon-m3"]["frame_left_mm"] == 1.8
    assert printers["photon-m3"]["display_mm"] == [163.84, 102.4]
    assert printers["photon-m3"]["pixel_mm"] == 0.04
    assert printers["photon-m3"]["lift_height_mm"] == 6.0


def test_calibration_values_move_the_image(client: TestClient) -> None:
    single = {**LAYOUT, "placements": LAYOUT["placements"][:1]}
    shifted = {"printer": "photon-m3", "outputs": ["mask"], "frame_left_mm": 5.0}
    plain = {"printer": "photon-m3", "outputs": ["mask"]}
    files = [("packages", ("basisplatine.zip", (DATA / "basisplatine.zip").read_bytes()))]
    a = _post(client, single, plain, files).content
    b = _post(client, single, shifted, files).content
    assert a != b


def test_unknown_printer(client: TestClient) -> None:
    _problem(_post(client, settings={"printer": "nope"}), 422, "exposure.unknown_printer")


def test_plate_larger_than_the_display(client: TestClient) -> None:
    big = {**LAYOUT, "plate": {"width_mm": 170.0, "height_mm": 100.0}}
    _problem(_post(client, layout=big), 422, "exposure.plate_too_large")
    # the calibration offset counts too: 160 mm plate and 5 mm offset do not fit on 163.84 mm
    _problem(_post(client, settings={**SETTINGS, "frame_left_mm": 5.0}), 422, "exposure.plate_too_large")


def test_smaller_plates_are_fine(client: TestClient) -> None:
    small = {**LAYOUT, "plate": {"width_mm": 75.0, "height_mm": 100.0}}
    single = {**small, "placements": small["placements"][:1]}
    assert _post(client, layout=single, files=_files()[:1]).status_code == 200


def test_unknown_board_in_layout(client: TestClient) -> None:
    layout = {**LAYOUT, "placements": [{**LAYOUT["placements"][0], "board_id": "ghost"}]}
    _problem(_post(client, layout=layout), 422, "exposure.unknown_board")


def test_invalid_package(client: TestClient) -> None:
    layout = {**LAYOUT, "placements": LAYOUT["placements"][:1]}
    files = [("packages", ("basisplatine.zip", b"nope"))]
    _problem(_post(client, layout=layout, files=files), 422, "exposure.invalid_package")
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("board.json", "{}")
        archive.writestr("copper.gbr", "")
    files = [("packages", ("basisplatine.zip", raw.getvalue()))]
    _problem(_post(client, layout=layout, files=files), 422, "exposure.invalid_package")


def test_unreadable_copper(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_path: Path) -> None:
        raise ValueError("cannot parse")

    monkeypatch.setattr("exposure.boards.GerberFile.open", broken)
    layout = {**LAYOUT, "placements": LAYOUT["placements"][:1]}
    files = [("packages", ("basisplatine.zip", (DATA / "basisplatine.zip").read_bytes()))]
    _problem(_post(client, layout=layout, files=files), 422, "exposure.unreadable_copper")


def test_invalid_settings(client: TestClient) -> None:
    _problem(_post(client, settings={"printer": "photon-m3", "exposure_s": 0}), 422, "common.invalid_request")
    _problem(_post(client, settings={"printer": "photon-m3", "holes": "all"}), 422, "common.invalid_request")
    _problem(_post(client, settings={"printer": "photon-m3", "outputs": []}), 422, "common.invalid_request")
    response = client.post("/v1/masks", files=_files(), data={"layout": "{", "settings": "{}"})
    _problem(response, 422, "common.invalid_request")


def test_isolated_request() -> None:
    isolated = TestClient(create_app(Settings(isolate=True)))
    files = [("packages", ("basisplatine.zip", (DATA / "basisplatine.zip").read_bytes()))]
    layout = {**LAYOUT, "placements": LAYOUT["placements"][:1]}
    assert _post(isolated, layout=layout, files=files).status_code == 200
