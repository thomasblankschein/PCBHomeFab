import io
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pcbhomefab import pm3
from pcbhomefab.service.api import create_app
from pcbhomefab.service.config import Settings
from pcbhomefab.service.store import FAILED, JobStore
from pcbhomefab.service.worker import process_next

DATA = Path(__file__).parent / "data"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_files=3,
        max_boards=50,
        rate_limit_per_hour=5,
        embedded_workers=0,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        yield test_client  # type: ignore[misc]


def _zip(name: str) -> bytes:
    return (DATA / name).read_bytes()


def _post(client: TestClient, *uploads: tuple[str, bytes], counts: list[str] | None = None, **fields: str):  # type: ignore[no-untyped-def]
    files = [("boards", (name, data, "application/zip")) for name, data in uploads]
    data: dict[str, object] = {**fields}
    if counts is not None:
        data["counts"] = counts
    return client.post("/api/jobs", files=files, data=data)


def test_job_from_upload_to_download(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    response = _post(
        client,
        ("base.zip", _zip("basisplatine.zip")),
        ("node.zip", _zip("fuehlerknoten.zip")),
        counts=["1", "3"],
        exposure_s="90",
    )
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "queued" and job["page"] == f"/jobs/{job['id']}"
    assert client.get(job["api"]).json()["status"] == "queued"

    assert process_next(JobStore(settings), settings, isolated=False)
    status = client.get(job["api"]).json()
    assert status["status"] == "done" and status["error"] is None
    names = {f["name"] for f in status["files"]}
    assert {"mask.png", "mask_preview.png", "exposure.pm3", "mill_gcode.zip", "mill_preview.svg"} <= names
    assert "mill/1_drill_0.8mm.nc" in names

    pm3_file = tmp_path / "downloaded.pm3"
    pm3_file.write_bytes(client.get(f"{job['api']}/files/exposure.pm3").content)
    info = pm3.read_pm3(pm3_file)
    assert info.exposure_s == 90 and info.machine_name == "Anycubic Photon M3"

    bundle = zipfile.ZipFile(io.BytesIO(client.get(f"{job['api']}/files/mill_gcode.zip").content))
    assert len(bundle.namelist()) == 3
    preview = client.get(f"{job['api']}/files/mask_preview.png")
    assert preview.headers["content-type"] == "image/png" and preview.headers["content-disposition"].startswith(
        "inline"
    )
    assert client.get(f"{job['api']}/files/exposure.pm3").headers["content-disposition"].startswith("attachment")
    page = client.get(job["page"]).text
    assert "exposure.pm3" in page and "mask_preview.png" in page


def test_job_page_while_queued_refreshes(client: TestClient) -> None:
    job = _post(client, ("node.zip", _zip("fuehlerknoten.zip"))).json()
    page = client.get(job["page"])
    assert page.status_code == 200 and 'http-equiv="refresh"' in page.text


def test_invalid_gerber_makes_the_job_fail_with_a_message(client: TestClient, settings: Settings) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "no gerber here")
    job = _post(client, ("bad.zip", buffer.getvalue())).json()
    assert process_next(JobStore(settings), settings, isolated=False)
    status = client.get(job["api"]).json()
    assert status["status"] == FAILED and "bottom copper" in status["error"]
    assert "bottom copper" in client.get(job["page"]).text


def test_upload_validation(client: TestClient) -> None:
    node = _zip("fuehlerknoten.zip")
    assert _post(client, ("a.zip", b"x" * (2 * 1024 * 1024))).status_code == 413
    assert _post(client, ("a.zip", b"not a zip")).status_code == 422
    assert _post(client, ("a.zip", node), counts=["1", "2"]).status_code == 422
    assert _post(client, ("a.zip", node), counts=["0"]).status_code == 422
    assert _post(client, ("a.zip", node), counts=["51"]).status_code == 422
    assert _post(client, *[(f"{i}.zip", node) for i in range(4)]).status_code == 422
    assert _post(client, ("a.zip", node), exposure="false", mill_gcode="false").status_code == 422
    assert _post(client, ("a.zip", node), exposure_s="0").status_code == 422
    assert _post(client, ("a.zip", node), holes="bogus").status_code == 422


def test_unknown_jobs_and_files(client: TestClient) -> None:
    assert client.get("/api/jobs/doesnotexist").status_code == 404
    assert client.get("/api/jobs/" + "a" * 22).status_code == 404
    assert client.get("/jobs/" + "a" * 22).status_code == 404
    job = _post(client, ("node.zip", _zip("fuehlerknoten.zip"))).json()
    assert client.get(f"{job['api']}/files/exposure.pm3").status_code == 404  # not done yet
    assert client.get(f"{job['api']}/files/../../../etc/passwd").status_code == 404


def test_path_traversal_in_file_name_is_refused(client: TestClient, settings: Settings) -> None:
    job = _post(client, ("node.zip", _zip("fuehlerknoten.zip"))).json()
    process_next(JobStore(settings), settings, isolated=False)
    (settings.data_dir / "secret.txt").write_text("secret")
    for name in ("..%2F..%2Fsecret.txt", "../../secret.txt", "mill/../../../secret.txt"):
        assert client.get(f"{job['api']}/files/{name}").status_code == 404


def test_rate_limit(client: TestClient) -> None:
    node = _zip("fuehlerknoten.zip")
    codes = [_post(client, ("n.zip", node)).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]


def test_queue_limit(settings: Settings) -> None:
    small = replace(settings, max_queued=1, rate_limit_per_hour=50)
    with TestClient(create_app(small)) as client:
        node = _zip("fuehlerknoten.zip")
        assert _post(client, ("n.zip", node)).status_code == 201
        assert _post(client, ("n.zip", node)).status_code == 503


def test_profiles_endpoint(client: TestClient) -> None:
    data = client.get("/api/profiles").json()
    assert data["printers"]["photon-m3"]["resolution"] == [4096, 2560]
    assert data["printers"]["photon-m3"]["border_mm"] == 1.0
    assert data["mills"]["3018pro"]["max_spindle_rpm"] == 20000
    tools = client.get("/api/tools").json()
    assert [t["diameter_mm"] for t in tools["tools"] if t["kind"] == "drill"] == [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
    assert client.get("/healthz").json() == {"status": "ok"}


def test_isolated_worker_and_timeout(settings: Settings) -> None:
    store = JobStore(settings)
    with TestClient(create_app(settings)) as client:
        job = _post(client, ("node.zip", _zip("fuehlerknoten.zip"))).json()
        assert process_next(store, settings, isolated=True)
        assert client.get(job["api"]).json()["status"] == "done"
        slow = replace(settings, job_timeout_s=0.01)
        job2 = _post(client, ("node.zip", _zip("fuehlerknoten.zip"))).json()
        assert process_next(store, slow, isolated=True)
        status = client.get(job2["api"]).json()
        assert status["status"] == FAILED and "longer" in status["error"]


def test_store_claims_oldest_first_and_requeues(settings: Settings) -> None:
    store = JobStore(settings)
    store.create("a" * 22, {"k": 1}, "c")
    time.sleep(0.01)
    store.create("b" * 22, {"k": 2}, "c")
    first = store.claim_next()
    assert first is not None and first.id == "a" * 22
    assert store.requeue_stale(-1) == 1  # everything running counts as stale
    again = store.claim_next()
    assert again is not None and again.id == "a" * 22


def test_expired_jobs_are_deleted(settings: Settings) -> None:
    store = JobStore(replace(settings, job_ttl_s=-1))
    store.create("c" * 22, {}, "c")
    folder = store.job_dir("c" * 22)
    folder.mkdir(parents=True)
    (folder / "x.txt").write_text("x")
    assert store.get("c" * 22) is None
    assert store.delete_expired() == 1
    assert not folder.exists()


def test_embedded_worker_end_to_end(settings: Settings) -> None:
    live = replace(settings, embedded_workers=1)
    with TestClient(create_app(live)) as client:
        job = _post(client, ("node.zip", _zip("fuehlerknoten.zip")), counts=["2"]).json()
        deadline = time.time() + 60
        status = "queued"
        while time.time() < deadline and status not in ("done", "failed"):
            time.sleep(0.5)
            status = client.get(job["api"]).json()["status"]
        assert status == "done"
