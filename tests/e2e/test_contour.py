"""End to end: a board with rounded corners and a round cutout is milled along its real Edge.Cuts contour.

Usage:  PCBHOMEFAB_URL=http://localhost pytest tests/e2e
"""

import io
import os
import re
import time
import zipfile
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("PCBHOMEFAB_URL", "http://localhost").rstrip("/")

HEAD = "%TF.FileFunction,Profile,NP*%\n%FSLAX46Y46*%\n%MOMM*%\n%LPD*%\nG01*\n%ADD10C,0.050000*%\nD10*\n"


def _mm(value: float) -> str:
    return f"{round(value * 1e6):d}"


def _line(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"X{_mm(x1)}Y{_mm(y1)}D02*\nG01*\nX{_mm(x2)}Y{_mm(y2)}D01*\n"


def _arc(x1: float, y1: float, x2: float, y2: float, cx: float, cy: float) -> str:
    return f"X{_mm(x1)}Y{_mm(y1)}D02*\nG75*\nG03*\nX{_mm(x2)}Y{_mm(y2)}I{_mm(cx - x1)}J{_mm(cy - y1)}D01*\nG01*\n"


def _outline() -> str:
    """30 x 20 mm, corner radius 3 mm, a round cutout of 6 mm diameter in the middle."""
    x0, y0, w, h, r = 10.0, -40.0, 30.0, 20.0, 3.0
    return (
        _line(x0 + r, y0, x0 + w - r, y0)
        + _arc(x0 + w - r, y0, x0 + w, y0 + r, x0 + w - r, y0 + r)
        + _line(x0 + w, y0 + r, x0 + w, y0 + h - r)
        + _arc(x0 + w, y0 + h - r, x0 + w - r, y0 + h, x0 + w - r, y0 + h - r)
        + _line(x0 + w - r, y0 + h, x0 + r, y0 + h)
        + _arc(x0 + r, y0 + h, x0, y0 + h - r, x0 + r, y0 + h - r)
        + _line(x0, y0 + h - r, x0, y0 + r)
        + _arc(x0, y0 + r, x0 + r, y0, x0 + r, y0 + r)
        + _arc(x0 + 18, y0 + 10, x0 + 18, y0 + 10, x0 + 15, y0 + 10)
    )


def _board_zip() -> bytes:
    source = zipfile.ZipFile(ROOT / "tests" / "data" / "fuehlerknoten.zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for entry in source.infolist():
            content = source.read(entry)
            if entry.filename.endswith("Edge_Cuts.gbr"):
                content = (HEAD + _outline() + "M02*\n").encode()
            archive.writestr(entry.filename, content)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    http = httpx.Client(base_url=BASE, timeout=60)
    try:
        http.get("/healthz").raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"no PCBHomeFab stack at {BASE}")
    return http


def test_contour_with_cutout_is_milled(client: httpx.Client) -> None:
    created = client.post("/api/v1/jobs", files=[("boards", ("round.zip", _board_zip(), "application/zip"))], data={"plate": "160x100"})
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    state: dict = {}
    for _ in range(120):
        state = client.get(f"/api/v1/jobs/{job_id}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert state["status"] == "done", state
    assert state["params"]["boards"][0]["width_mm"] == 30.0 and state["params"]["boards"][0]["height_mm"] == 20.0

    program = next(f["name"] for f in state["files"] if f["name"].endswith("_mill_1.0mm.nc"))
    code = client.get(f"/api/v1/jobs/{job_id}/files/{program}").text
    moves = [(float(x), float(y)) for x, y in re.findall(r"^G1 X(-?[\d.]+) Y(-?[\d.]+) F", code, re.M)]
    assert len(moves) > 150  # the arcs of the corners and of the cutout are many short moves

    # the board is placed at x 3..33, y 3..23 and mirrored in X on the mill (flip x): x 127..157
    cutout = [p for p in moves if 127 + 15 - 3 < p[0] < 127 + 15 + 3 and 13 - 3 < p[1] < 13 + 3]
    assert cutout, "no moves inside the cutout"
    cut_radii = {round(((x - 142) ** 2 + (y - 13) ** 2) ** 0.5, 1) for x, y in cutout}
    assert cut_radii == {2.5}  # 3 mm cutout radius minus 0.5 mm tool radius

    preview = client.get(f"/api/v1/jobs/{job_id}/files/mill_preview.svg").text
    assert "<path" in preview


def test_preview_endpoints_for_the_editor(client: httpx.Client) -> None:
    """The editor asks for the board shape and the layout before a job exists."""
    info = client.post("/api/v1/boards", files={"file": ("round.zip", _board_zip(), "application/zip")})
    assert info.status_code == 200, info.text
    board = info.json()
    assert (board["width_mm"], board["height_mm"]) == (30.0, 20.0)
    assert len(board["contour"]["cutouts"]) == 1 and len(board["contour"]["outer"]) > 30

    layout = client.post(
        "/api/v1/layouts",
        json={"plate": "160x100", "gap_mm": 3, "margin_mm": 3, "boards": [{"id": "b0", "width_mm": 30, "height_mm": 20, "count": 4}]},
    )
    assert layout.status_code == 200, layout.text
    assert [(p["x_mm"], p["y_mm"]) for p in layout.json()["placements"]] == [(3, 3), (36, 3), (69, 3), (102, 3)]

    too_many = client.post(
        "/api/v1/layouts",
        json={"plate": "160x100", "boards": [{"id": "b0", "width_mm": 30, "height_mm": 20, "count": 100}]},
    )
    assert too_many.status_code == 422 and too_many.json()["code"] == "panel.does_not_fit"


def test_static_pages_and_scripts(client: httpx.Client) -> None:
    for path, marker in (("/", "editor.js"), ("/tools", "tools.js")):
        response = client.get(path)
        assert response.status_code == 200 and marker in response.text, path
    assert client.get("/js/geometry.js").status_code == 200
    headers = client.get("/").headers
    assert "default-src 'self'" in headers["content-security-policy"]
