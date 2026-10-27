"""Stand-ins for the other services. They answer like the contracts say, so ``jobs`` is tested without them."""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Callable
from typing import Any

import httpx

ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def make_zip(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(zipfile.ZipInfo(name, ZIP_TIME), content)
    return buffer.getvalue()


def problem(status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> httpx.Response:
    body = {"type": "about:blank", "title": "Problem", "status": status, "code": code, "detail": detail}
    return httpx.Response(status, json=body, headers={"content-type": "application/problem+json", **(headers or {})})


class Downstream:
    """Fake ingest, panel, exposure and mill. ``override`` replaces the answer of one service."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.override: dict[str, Callable[[httpx.Request], httpx.Response]] = {}

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle), timeout=5)

    def handle(self, request: httpx.Request) -> httpx.Response:
        service = request.url.host
        self.calls.append((service, request.url.path, request.headers.get("x-request-id")))
        if service in self.override:
            return self.override[service](request)
        handler = getattr(self, f"_{service}")
        response: httpx.Response = handler(request)
        return response

    # --- ingest ---------------------------------------------------------------------------------------------

    def _ingest(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        if b"not a zip" in body:
            return problem(422, "ingest.invalid_zip", "The upload is not a valid ZIP file.")
        match = re.search(rb'name="name"\r\n\r\n(.*?)\r\n--', body, re.S)
        name = match.group(1).decode() if match else "board"
        board = {
            "schema_version": 1,
            "name": name,
            "outline": {"xmin": 0, "ymin": 0, "xmax": 10, "ymax": 26},
            "width_mm": 10.0,
            "height_mm": 26.0,
            "holes": [],
        }
        package = make_zip({"copper.gbr": "G04*\nM02*\n", "board.json": json.dumps(board)})
        return httpx.Response(200, content=package, headers={"content-type": "application/zip"})

    # --- panel ----------------------------------------------------------------------------------------------

    def _panel(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        placements = []
        x = 3.0
        for board in body["boards"]:
            for _ in range(board["count"]):
                placements.append({"board_id": board["id"], "x_mm": x, "y_mm": 3.0, "rotation_deg": 0})
                x += board["width_mm"] + body["gap_mm"]
        return httpx.Response(200, json={"plate": body["plate"], "placements": placements})

    # --- exposure and mill ----------------------------------------------------------------------------------

    def _exposure(self, request: httpx.Request) -> httpx.Response:
        settings = _form_field(request, "settings")
        pm3 = b"ANYCUBIC" + str(settings.get("exposure_s")).encode()
        available = {
            "mask": ("mask.png", b"png"),
            "preview": ("mask_preview.png", b"preview"),
            "pm3": ("exposure.pm3", pm3),
        }
        available["copper"] = ("copper.png", b"copper")
        package = make_zip(dict(available[o] for o in settings.get("outputs", ["mask", "preview", "pm3"])))
        return httpx.Response(200, content=package, headers={"content-type": "application/zip"})

    def _mill(self, request: httpx.Request) -> httpx.Response:
        package = make_zip(
            {
                "1_drill_0.8mm.nc": "M3 S20000\nM5\nM30\n",
                "2_mill_1.0mm.nc": "M3 S20000\nM5\nM30\n",
                "preview.svg": "<svg></svg>",
                "programs.json": json.dumps({"programs": []}),
            }
        )
        return httpx.Response(200, content=package, headers={"content-type": "application/zip"})


def _form_field(request: httpx.Request, name: str) -> dict[str, Any]:
    """The JSON text of a multipart form field."""
    marker = f'name="{name}"'.encode()
    content = request.content
    start = content.index(marker)
    start = content.index(b"\r\n\r\n", start) + 4
    end = content.index(b"\r\n--", start)
    value: dict[str, Any] = json.loads(content[start:end])
    return value
