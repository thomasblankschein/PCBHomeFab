import json

import pytest
from fastapi.testclient import TestClient

from conftest import CONTRACTS, contract_operations, validate
from panel.common import Problem
from panel.layout import BoardSpec, pack
from panel.main import Settings, create_app

BASE = BoardSpec("basisplatine", 28.2, 38.0, 1)
NODE = BoardSpec("fuehlerknoten", 10.0, 26.0, 15)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(Settings(isolate=False)))


def test_pack_positions() -> None:
    placements = pack([BASE, NODE], 160, 100, gap_mm=3, margin_mm=3)
    positions = [(p.x_mm, p.y_mm) for p in placements]
    assert positions[0] == (3.0, 3.0)
    assert positions[1:10] == [(34.2 + 13 * i, 3.0) for i in range(9)]
    assert positions[10:] == [(3.0 + 13 * i, 44.0) for i in range(6)]
    assert {p.board_id for p in placements[1:]} == {"fuehlerknoten"}


def test_pack_rejects_too_many() -> None:
    with pytest.raises(Problem) as caught:
        pack([BoardSpec("n", 10, 26, 100)], 160, 100, 3, 3)
    assert caught.value.code == "panel.does_not_fit"


def test_pack_rejects_too_wide() -> None:
    with pytest.raises(Problem) as caught:
        pack([BoardSpec("wide", 160, 10, 1)], 160, 100, 3, 3)
    assert caught.value.code == "panel.board_too_wide"


def test_routes_match_the_contract(client: TestClient) -> None:
    implemented = {
        (method, route.path)
        for route in client.app.routes  # type: ignore[attr-defined]
        for method in getattr(route, "methods", None) or ()
    }
    assert contract_operations() <= implemented


def test_example_request_gives_the_example_layout(client: TestClient) -> None:
    request = json.loads((CONTRACTS / "examples" / "layout-request.json").read_text())
    validate("layout-request", request)
    response = client.post("/v1/layouts", json=request)
    assert response.status_code == 200
    validate("layout", response.json())
    assert response.json() == json.loads((CONTRACTS / "examples" / "layout.json").read_text())


def test_defaults_for_gap_and_margin(client: TestClient) -> None:
    body = {
        "panel": {"width_mm": 160, "height_mm": 100},
        "boards": [{"id": "a", "width_mm": 10, "height_mm": 10, "count": 2}],
    }
    placements = client.post("/v1/layouts", json=body).json()["placements"]
    assert [(p["x_mm"], p["y_mm"]) for p in placements] == [(3.0, 3.0), (16.0, 3.0)]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"panel": {"width_mm": 160, "height_mm": 100}, "boards": []},
        {
            "panel": {"width_mm": 160, "height_mm": 100},
            "boards": [{"id": "../x", "width_mm": 1, "height_mm": 1, "count": 1}],
        },
        {
            "panel": {"width_mm": -1, "height_mm": 100},
            "boards": [{"id": "a", "width_mm": 1, "height_mm": 1, "count": 1}],
        },
        {
            "panel": {"width_mm": 160, "height_mm": 100},
            "boards": [{"id": "a", "width_mm": 1, "height_mm": 1, "count": 0}],
        },
    ],
)
def test_invalid_requests_are_problems(client: TestClient, body: dict) -> None:
    response = client.post("/v1/layouts", json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    validate("problem", response.json())
    assert response.json()["code"] == "common.invalid_request"


def test_layout_errors_are_problems(client: TestClient) -> None:
    body = {
        "panel": {"width_mm": 160, "height_mm": 100},
        "boards": [{"id": "n", "width_mm": 10, "height_mm": 26, "count": 100}],
    }
    response = client.post("/v1/layouts", json=body)
    assert response.status_code == 422
    validate("problem", response.json())
    assert response.json()["code"] == "panel.does_not_fit"


def test_too_many_boards_limit() -> None:
    small = TestClient(create_app(Settings(max_boards=3, isolate=False)))
    body = {
        "panel": {"width_mm": 160, "height_mm": 100},
        "boards": [{"id": "a", "width_mm": 1, "height_mm": 1, "count": 4}],
    }
    assert small.post("/v1/layouts", json=body).status_code == 422


def test_isolated_request() -> None:
    isolated = TestClient(create_app(Settings(isolate=True)))
    request = json.loads((CONTRACTS / "examples" / "layout-request.json").read_text())
    assert isolated.post("/v1/layouts", json=request).status_code == 200
    bad = {
        "panel": {"width_mm": 160, "height_mm": 100},
        "boards": [{"id": "wide", "width_mm": 160, "height_mm": 10, "count": 1}],
    }
    assert isolated.post("/v1/layouts", json=bad).json()["code"] == "panel.board_too_wide"
