"""Positioning marks against a running stack: marks in the copper picture, X0 Y0 of the G-code at the lower left mark."""

import io
import os
import re
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("PCBHOMEFAB_URL", "http://localhost").rstrip("/")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    http = httpx.Client(base_url=BASE, timeout=60)
    try:
        http.get("/healthz").raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"no PCBHomeFab stack at {BASE}")
    return http


def _job(client: httpx.Client, **fields: str) -> dict:
    board = (ROOT / "tests" / "data" / "fuehlerknoten.zip").read_bytes()
    data = {"plate": "160x100", "margin_mm": "5", "counts": "3", **fields}
    created = client.post(
        "/api/v1/jobs",
        files=[("boards", ("node.zip", board, "application/zip"))],
        data=data,
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


@pytest.mark.parametrize("flip", ["x", "y", "none"])
def test_second_mark_is_named_in_every_program(client: httpx.Client, flip: str) -> None:
    job = _job(client, flip=flip)
    marks = job["params"]["marks"]
    assert marks["second_mm"] == {"x_mm": 156.0, "y_mm": 96.0}
    programs = [f["name"] for f in job["files"] if f["name"].endswith(".nc")]
    assert programs
    for name in programs:
        code = _file(client, job, name).decode()
        assert "(Second positioning mark, upper right: X156.000 Y96.000)" in code
        assert "centre of the lower left positioning mark" in code


def test_origin_moves_to_the_mark_and_the_copper_picture_shows_the_marks(
    client: httpx.Client,
) -> None:
    with_marks = _job(client, flip="x")
    without = _job(client, flip="x", marks="false")
    assert without["params"]["marks"] is None

    def moves(job: dict) -> set[tuple[float, float]]:
        name = next(
            f["name"] for f in job["files"] if f["name"].endswith("_drill_0.8mm.nc")
        )
        code = _file(client, job, name).decode()
        return {
            (round(float(x), 3), round(float(y), 3))
            for x, y in re.findall(r"^G0 X(-?[\d.]+) Y(-?[\d.]+)", code, re.M)
        }

    shifted = {
        (round(x - 2.0, 3), round(y - 2.0, 3)) for x, y in moves(without) - {(0.0, 0.0)}
    }
    assert shifted == moves(with_marks) - {(0.0, 0.0)}

    copper = Image.open(io.BytesIO(_file(client, with_marks, "copper.png")))
    plain = Image.open(io.BytesIO(_file(client, without, "copper.png")))
    # flip x: the marks are at the upper left (2, 98) and the lower right (158, 2) of the design view, 10 px/mm
    assert copper.getpixel((14, 14))[3] == 255 and plain.getpixel((14, 14))[3] == 0
    assert copper.getpixel((1580 + 6, 1000 - 20 + 6))[3] == 255
    mask = Image.open(io.BytesIO(_file(client, with_marks, "mask.png"))).convert("L")
    assert mask.getbbox() is not None


def test_marks_need_a_wide_margin(client: httpx.Client) -> None:
    board = (ROOT / "tests" / "data" / "fuehlerknoten.zip").read_bytes()
    refused = client.post(
        "/api/v1/jobs",
        files=[("boards", ("node.zip", board, "application/zip"))],
        data={"plate": "160x100", "margin_mm": "3"},
    )
    assert refused.status_code == 422 and refused.json()["code"] == "jobs.invalid_marks"
