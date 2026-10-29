"""Stand-ins for the other services. They answer like the contracts say, so ``jobs`` is tested without them."""

from __future__ import annotations

import io
import json
import re
import struct
import zipfile
import zlib
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


def tiny_png(width: int = 8, height: int = 5) -> bytes:
    """A small valid PNG (grey, black), for the pictures of the fake services."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes(width) for _ in range(height))
    signature = b"\x89PNG\r\n\x1a\n"
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


MILL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500">'
    '<rect x="0" y="0" width="800" height="500" fill="#c9a06a" stroke="black"/>'
    '<path d="M100 100 L200 100 L200 200 L100 200 Z M120 120 L150 120 L150 150 Z" fill-rule="evenodd" fill="#2d6a4f" '
    'stroke="#d00000" stroke-width="1"/>'
    '<circle cx="110" cy="110" r="2" fill="#ffd60a"/><circle cx="190" cy="190" r="2" fill="#ffd60a"/>'
    '<circle cx="150" cy="170" r="3" fill="#00b4d8"/></svg>'
)
PROGRAMS = {
    "programs": [
        {
            "filename": "1_drill_0.8mm.nc",
            "title": "t",
            "tool": "drill-0.8",
            "holes": 2,
            "outlines": 0,
            "estimated_s": 75.4,
        },
        {
            "filename": "2_mill_1.0mm.nc",
            "title": "t",
            "tool": "endmill-1.0",
            "holes": 1,
            "outlines": 1,
            "estimated_s": 3725,
        },
    ]
}


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
        return httpx.Response(200, json={"panel": body["panel"], "placements": placements})

    # --- exposure and mill ----------------------------------------------------------------------------------

    def _exposure(self, request: httpx.Request) -> httpx.Response:
        settings = _form_field(request, "settings")
        pm3 = b"ANYCUBIC" + str(settings.get("exposure_s")).encode()
        available = {
            "mask": ("mask.png", b"png"),
            "preview": ("mask_preview.png", tiny_png()),
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
                "preview.svg": MILL_SVG,
                "programs.json": json.dumps(PROGRAMS),
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
