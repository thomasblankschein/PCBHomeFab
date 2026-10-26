import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import contract_operations, validate
from ingest.main import Settings, create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(Settings(isolate=False)))


def test_routes_match_the_contract(client: TestClient) -> None:
    implemented = {
        (method, route.path)
        for route in client.app.routes  # type: ignore[attr-defined]
        for method in getattr(route, "methods", None) or ()
        if route.path.startswith(("/v1/", "/healthz"))
    }
    assert contract_operations() <= implemented


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_create_package(client: TestClient, data_dir: Path) -> None:
    upload = (data_dir / "fuehlerknoten.zip").read_bytes()
    response = client.post("/v1/packages", files={"file": ("n.zip", upload)}, data={"name": "node"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as package:
        assert sorted(package.namelist()) == ["board.json", "copper.gbr"]


def test_request_id_is_returned_and_kept(client: TestClient) -> None:
    assert client.get("/healthz", headers={"X-Request-Id": "abc-123"}).headers["x-request-id"] == "abc-123"
    assert len(client.get("/healthz").headers["x-request-id"]) >= 8


def test_bad_zip_is_a_problem(client: TestClient) -> None:
    response = client.post("/v1/packages", files={"file": ("n.zip", b"nope")})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    validate("problem", response.json())
    assert response.json()["code"] == "ingest.invalid_zip"


def test_missing_file_is_a_problem(client: TestClient) -> None:
    response = client.post("/v1/packages")
    assert response.status_code == 422
    validate("problem", response.json())
    assert response.json()["code"] == "common.invalid_request"


def test_bad_name_is_a_problem(client: TestClient) -> None:
    response = client.post("/v1/packages", files={"file": ("n.zip", b"x")}, data={"name": "../x"})
    assert response.status_code == 422 and response.json()["code"] == "common.invalid_request"


def test_unknown_path_is_a_problem(client: TestClient) -> None:
    response = client.get("/v1/nothing")
    assert response.status_code == 404
    validate("problem", response.json())
    assert response.json()["code"] == "common.not_found"


def test_too_large_upload() -> None:
    small = TestClient(create_app(Settings(max_upload_bytes=1000, isolate=False)))
    response = small.post("/v1/packages", files={"file": ("n.zip", b"0" * 2000)})
    assert response.status_code == 413
    validate("problem", response.json())
    assert response.json()["code"] == "common.too_large"


def test_isolated_request_in_its_own_process(data_dir: Path) -> None:
    isolated = TestClient(create_app(Settings(isolate=True, timeout_s=60)))
    upload = (data_dir / "fuehlerknoten.zip").read_bytes()
    assert isolated.post("/v1/packages", files={"file": ("n.zip", upload)}).status_code == 200
    bad = isolated.post("/v1/packages", files={"file": ("n.zip", b"nope")})
    assert bad.status_code == 422 and bad.json()["code"] == "ingest.invalid_zip"


def test_busy_service_answers_503() -> None:
    app = create_app(Settings(max_parallel=1, isolate=False))
    assert app.state.isolation._slots.acquire(blocking=False)  # take the only slot
    response = TestClient(app).post("/v1/packages", files={"file": ("n.zip", b"x")})
    assert response.status_code == 503
    assert response.json()["code"] == "common.busy"
    assert response.headers["retry-after"] == "5"
    validate("problem", response.json())
