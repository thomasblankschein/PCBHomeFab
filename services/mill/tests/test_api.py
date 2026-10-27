import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import CONTRACTS, contract_operations, validate
from mill.main import Settings, create_app

DATA = Path(__file__).parent / "data"
LAYOUT = json.loads((CONTRACTS / "examples" / "layout.json").read_text())
SETTINGS = json.loads((CONTRACTS / "examples" / "mill-settings.json").read_text())


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(Settings(isolate=False)))


def _files() -> list[tuple[str, tuple[str, bytes]]]:
    return [("packages", (f"{n}.zip", (DATA / f"{n}.zip").read_bytes())) for n in ("basisplatine", "fuehlerknoten")]


def _post(client: TestClient, layout: Any = LAYOUT, settings: Any = SETTINGS, files: Any = None) -> Any:
    return client.post(
        "/v1/programs",
        files=_files() if files is None else files,
        data={"layout": json.dumps(layout), "settings": json.dumps(settings)},
    )


def test_routes_match_the_contract(client: TestClient) -> None:
    implemented = {
        (method, route.path)
        for route in client.app.routes  # type: ignore[attr-defined]
        for method in getattr(route, "methods", None) or ()
    }
    assert contract_operations() <= implemented


def test_example_request_gives_programs(client: TestClient) -> None:
    validate("layout", LAYOUT)
    validate("mill-settings", SETTINGS)
    response = _post(client)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == [
            "1_drill_0.8mm.nc",
            "2_drill_1.0mm.nc",
            "3_mill_1.0mm.nc",
            "preview.svg",
            "programs.json",
        ]
        index = json.loads(archive.read("programs.json"))
        assert archive.read("preview.svg").startswith(b"<svg")
    validate("programs", index)
    assert [p["holes"] for p in index["programs"]] == [100, 52, 2]


def test_response_is_deterministic(client: TestClient) -> None:
    assert _post(client).content == _post(client).content


def test_profiles_and_tools(client: TestClient) -> None:
    profiles = client.get("/v1/profiles").json()
    assert profiles["mills"]["3018pro"]["max_spindle_rpm"] == 20000
    assert profiles["mills"]["3018pro"]["safe_z_mm"] == 3.0
    assert profiles["mills"]["3018pro"]["tool_change_z_mm"] == 50.0
    assert profiles["mills"]["3018pro"]["default_thickness_mm"] == 1.5
    tools = client.get("/v1/tools").json()
    assert tools["source"] == "built-in"
    assert "drill-0.8" in [t["id"] for t in tools["tools"]]


def _problem(response: Any, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    validate("problem", response.json())
    assert response.json()["code"] == code


def test_unknown_mill(client: TestClient) -> None:
    _problem(_post(client, settings={"mill": "nope"}), 422, "mill.unknown_mill")


def test_unknown_board_in_layout(client: TestClient) -> None:
    layout = {**LAYOUT, "placements": [{**LAYOUT["placements"][0], "board_id": "ghost"}]}
    _problem(_post(client, layout=layout), 422, "mill.unknown_board")


def test_invalid_package(client: TestClient) -> None:
    files = [("packages", ("basisplatine.zip", b"not a zip"))]
    _problem(_post(client, files=files), 422, "mill.invalid_package")
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("board.json", "{}")
    _problem(_post(client, files=[("packages", ("basisplatine.zip", raw.getvalue()))]), 422, "mill.invalid_package")


def test_invalid_json_and_settings(client: TestClient) -> None:
    response = client.post("/v1/programs", files=_files(), data={"layout": "{", "settings": "{}"})
    _problem(response, 422, "common.invalid_request")
    _problem(_post(client, settings={"mill": "3018pro", "thickness_mm": 99}), 422, "common.invalid_request")
    _problem(_post(client, settings={"mill": "3018pro", "extra": 1}), 422, "common.invalid_request")


def test_package_file_name_must_be_a_board_id(client: TestClient) -> None:
    files = [("packages", ("bad name!.zip", (DATA / "basisplatine.zip").read_bytes()))]
    _problem(_post(client, files=files), 422, "common.invalid_request")


def test_hole_without_drill_is_a_problem(client: TestClient) -> None:
    raw = io.BytesIO()
    board = {
        "schema_version": 1,
        "name": "odd",
        "outline": {"xmin": 0, "ymin": 0, "xmax": 10, "ymax": 10},
        "width_mm": 10,
        "height_mm": 10,
        "holes": [{"x_mm": 5, "y_mm": 5, "diameter_mm": 0.95, "plated": True}],
    }
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("board.json", json.dumps(board))
        archive.writestr("copper.gbr", "G04*\nM02*\n")
    layout = {**LAYOUT, "placements": [{"board_id": "odd", "x_mm": 3, "y_mm": 3, "rotation_deg": 0}]}
    _problem(_post(client, layout=layout, files=[("packages", ("odd.zip", raw.getvalue()))]), 422, "mill.no_drill")


def test_isolated_request() -> None:
    isolated = TestClient(create_app(Settings(isolate=True)))
    assert _post(isolated).status_code == 200
    _problem(_post(isolated, settings={"mill": "nope"}), 422, "mill.unknown_mill")


def test_positioning_marks(client: TestClient) -> None:
    marks = [{"x_mm": 2.0, "y_mm": 98.0, "voids": "tr-bl"}, {"x_mm": 158.0, "y_mm": 2.0, "voids": "tr-bl"}]
    validate("mill-settings", {**SETTINGS, "marks": marks})
    response = _post(client, settings={**SETTINGS, "marks": marks})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        index = json.loads(archive.read("programs.json"))
        code = archive.read("1_drill_0.8mm.nc").decode()
    validate("programs", index)
    assert index["marks"] == {"second_x_mm": 156.0, "second_y_mm": 96.0}
    assert "(Second positioning mark, upper right: X156.000 Y96.000)" in code


def test_marks_that_do_not_stand_diagonally_are_refused(client: TestClient) -> None:
    marks = [{"x_mm": 2.0, "y_mm": 2.0}, {"x_mm": 158.0, "y_mm": 2.0}]
    _problem(_post(client, settings={**SETTINGS, "marks": marks}), 422, "mill.invalid_marks")
    _problem(_post(client, settings={**SETTINGS, "marks": marks[:1]}), 422, "common.invalid_request")
