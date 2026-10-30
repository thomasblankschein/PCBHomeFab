"""End to end test against a running stack: the outputs must equal the golden outputs of the single-package code.

Usage:  PCBHOMEFAB_URL=http://localhost pytest tests/e2e
The test is skipped when no stack answers at PCBHOMEFAB_URL. It uses only the public REST API of the gateway.
"""

import hashlib
import io
import json
import os
import time
from pathlib import Path

import httpx
import pytest
from conftest import auth_headers
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "tests" / "golden" / "manifest.json").read_text())
BASE = os.environ.get("PCBHOMEFAB_URL", "http://localhost").rstrip("/")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    http = httpx.Client(base_url=BASE, timeout=60)
    try:
        http.get("/healthz").raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"no PCBHomeFab stack at {BASE}")
    http.headers.update(auth_headers(BASE))
    return http


@pytest.fixture(scope="module")
def job(client: httpx.Client) -> dict:
    params = GOLDEN["params"]
    files = [
        (
            "boards",
            (
                f"{b['name']}.zip",
                (ROOT / "tests" / "data" / b["file"]).read_bytes(),
                "application/zip",
            ),
        )
        for b in params["boards"]
    ]
    data: dict[str, object] = {"counts": [str(b["count"]) for b in params["boards"]]}
    for key, value in params.items():
        if key != "boards":
            data[key] = str(value).lower() if isinstance(value, bool) else str(value)
    created = client.post("/api/v1/jobs", files=files, data=data)
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    deadline = time.time() + 180
    while time.time() < deadline:
        state = client.get(f"/api/v1/jobs/{job_id}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert state["status"] == "done", state
    return {"id": job_id, "files": {f["name"]: f for f in state["files"]}}


def _fingerprint(name: str, content: bytes) -> str:
    if name.endswith(".png"):  # PNG bytes depend on the encoder, compare the pixels
        content = Image.open(io.BytesIO(content)).convert("L").tobytes()
    else:
        content = content.replace(
            b"\r\n", b"\n"
        )  # the golden files were made on Windows
    return hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize("name", sorted(GOLDEN["files"]))
def test_output_equals_golden(client: httpx.Client, job: dict, name: str) -> None:
    assert name in job["files"]
    response = client.get(f"/api/v1/jobs/{job['id']}/files/{name}")
    assert response.status_code == 200
    assert _fingerprint(name, response.content) == GOLDEN["files"][name]["sha256"]


def test_gcode_bundle_has_all_programs(client: httpx.Client, job: dict) -> None:
    import zipfile

    bundle = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/v1/jobs/{job['id']}/files/mill_gcode.zip").content)
    )
    expected = sorted(Path(n).name for n in GOLDEN["files"] if n.endswith(".nc"))
    assert sorted(bundle.namelist()) == expected


def test_pages_are_served(client: httpx.Client, job: dict) -> None:
    assert "PCBHomeFab" in client.get("/").text
    page = client.get(f"/jobs/{job['id']}")
    assert page.status_code == 200 and "job.js" in page.text
