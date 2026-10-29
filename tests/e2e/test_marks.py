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
    data = {"panel": "160x100", "margin_mm": "5", "counts": "3", **fields}
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
    second = job["params"]["marks"]["second_mm"]
    assert second["x_mm"] > 10 and second["y_mm"] > 10  # the other mark is far from the origin mark
    programs = [f["name"] for f in job["files"] if f["name"].endswith(".nc")]
    assert programs
    for name in programs:
        code = _file(client, job, name).decode()
        assert f"(Second positioning mark, upper right: X{second['x_mm']:.3f} Y{second['y_mm']:.3f})" in code
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

    origin = with_marks["params"]["marks"]["panel_origin_mm"]  # the lower left corner of the panel in G-code coordinates
    shifted = {
        (round(x + origin["x_mm"], 3), round(y + origin["y_mm"], 3)) for x, y in moves(without) - {(0.0, 0.0)}
    }
    assert shifted == moves(with_marks) - {(0.0, 0.0)}

    copper = Image.open(io.BytesIO(_file(client, with_marks, "copper.png")))
    plain = Image.open(io.BytesIO(_file(client, without, "copper.png")))
    # flip x: the second mark is at the upper left (2, 98) of the design view, 10 px/mm; the origin mark is next to the boards
    assert copper.getpixel((14, 14))[3] == 255 and plain.getpixel((14, 14))[3] == 0
    near = next(p for p in with_marks["params"]["marks"]["points"] if p["x_mm"] > 5)
    x, y = round(near["x_mm"] * 10), round((100 - near["y_mm"]) * 10)
    assert copper.getpixel((x + 6, y + 6))[3] == 255 and plain.getpixel((x + 6, y + 6))[3] == 0
    mask = Image.open(io.BytesIO(_file(client, with_marks, "mask.png"))).convert("L")
    assert mask.getbbox() is not None


def test_marks_need_a_wide_margin(client: httpx.Client) -> None:
    board = (ROOT / "tests" / "data" / "fuehlerknoten.zip").read_bytes()
    refused = client.post(
        "/api/v1/jobs",
        files=[("boards", ("node.zip", board, "application/zip"))],
        data={"panel": "160x100", "margin_mm": "3"},
    )
    assert refused.status_code == 422 and refused.json()["code"] == "jobs.invalid_marks"
