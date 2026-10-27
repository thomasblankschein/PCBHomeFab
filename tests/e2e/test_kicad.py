"""A KiCad PCB file against a running stack: the same job as from the Gerber export of the same board."""

import io
import os
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("PCBHOMEFAB_URL", "http://localhost").rstrip("/")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    http = httpx.Client(base_url=BASE, timeout=120)
    try:
        http.get("/healthz").raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"no PCBHomeFab stack at {BASE}")
    return http


def _job(client: httpx.Client, filename: str, content_type: str) -> dict:
    board = (ROOT / "tests" / "data" / filename).read_bytes()
    created = client.post(
        "/api/v1/jobs",
        files=[("boards", (filename, board, content_type))],
        data={"plate": "160x100", "margin_mm": "5", "counts": "2", "marks": "false"},
    )
    assert created.status_code == 201, created.text
    for _ in range(120):
        state = client.get(f"/api/v1/jobs/{created.json()['id']}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert state["status"] == "done", state
    return state


def _file(client: httpx.Client, job: dict, name: str) -> bytes:
    return client.get(f"/api/v1/jobs/{job['id']}/files/{name}").content


@pytest.mark.parametrize("name", ["fuehlerknoten", "basisplatine"])
def test_kicad_file_gives_the_same_job_as_the_gerber_export(client: httpx.Client, name: str) -> None:
    kicad = _job(client, f"{name}.kicad_pcb", "text/plain")
    gerber = _job(client, f"{name}.zip", "application/zip")
    assert kicad["params"]["boards"][0]["width_mm"] == gerber["params"]["boards"][0]["width_mm"]
    programs = sorted(f["name"] for f in gerber["files"] if f["name"].endswith(".nc"))
    assert programs == sorted(f["name"] for f in kicad["files"] if f["name"].endswith(".nc"))
    for program in programs:  # holes and outline are the same, so the programs are too
        assert _file(client, kicad, program) == _file(client, gerber, program)
    masks = [Image.open(io.BytesIO(_file(client, job, "mask.png"))).convert("L") for job in (kicad, gerber)]
    differing = sum(1 for v in ImageChops.difference(*masks).getdata() if v)
    assert differing < 0.002 * masks[0].size[0] * masks[0].size[1]
