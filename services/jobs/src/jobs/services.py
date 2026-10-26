"""Calls to the other services (ingest, panel, exposure, mill) over REST."""

from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from collections.abc import Callable
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger("jobs.services")
INTERNAL_ERROR = "Internal error while creating the files."
MAX_ATTEMPTS = 3
MAX_ZIP_ENTRIES = 64
MAX_ZIP_BYTES = 200 * 1024 * 1024


class UserError(Exception):
    """A service refused the data with a 4xx problem. ``code`` and ``message`` are safe to show to users."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)
        self.code = code
        self.message = message


class Unavailable(Exception):
    """A service cannot be reached or failed (5xx, timeout, bad answer). Details are only logged."""


class Services:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.call_timeout_s)

    # --- generic call -----------------------------------------------------------------------------------------

    def _call(self, method: str, url: str, request_id: str, **kwargs: Any) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self.client.request(method, url, headers={"X-Request-Id": request_id}, **kwargs)
            except httpx.HTTPError as exc:
                log.error("[%s] %s %s failed: %r", request_id, method, url, exc)
                raise Unavailable(url) from exc
            if response.status_code == 503 and attempt < MAX_ATTEMPTS - 1:  # busy: wait as asked and try again
                time.sleep(min(float(response.headers.get("retry-after", "2") or 2), 5.0))
                continue
            break
        assert response is not None
        if response.status_code < 400:
            return response
        problem = _problem(response)
        if problem is not None and 400 <= response.status_code < 500 and not problem[0].startswith("common."):
            raise UserError(*problem)
        log.error("[%s] %s %s answered %s: %s", request_id, method, url, response.status_code, response.text[:300])
        raise Unavailable(url)

    # --- the services -----------------------------------------------------------------------------------------

    def ingest(self, data: bytes, board_id: str, request_id: str) -> bytes:
        response = self._call(
            "POST",
            f"{self.settings.ingest_url}/v1/packages",
            request_id,
            files={"file": (f"{board_id}.zip", data, "application/zip")},
            data={"name": board_id},
        )
        return response.content

    def panel(self, request: dict[str, Any], request_id: str) -> dict[str, Any]:
        response = self._call("POST", f"{self.settings.panel_url}/v1/layouts", request_id, json=request)
        layout: dict[str, Any] = response.json()
        return layout

    def exposure(
        self, packages: dict[str, bytes], layout: dict[str, Any], settings: dict[str, Any], request_id: str
    ) -> dict[str, bytes]:
        response = self._call(
            "POST",
            f"{self.settings.exposure_url}/v1/masks",
            request_id,
            files=_package_parts(packages),
            data={"layout": json.dumps(layout), "settings": json.dumps(settings)},
        )
        allowed = re.compile(r"^(mask\.png|mask_preview\.png|exposure\.pm3)$")
        return read_zip(response.content, lambda name: bool(allowed.match(name)))

    def mill(
        self, packages: dict[str, bytes], layout: dict[str, Any], settings: dict[str, Any], request_id: str
    ) -> dict[str, bytes]:
        response = self._call(
            "POST",
            f"{self.settings.mill_url}/v1/programs",
            request_id,
            files=_package_parts(packages),
            data={"layout": json.dumps(layout), "settings": json.dumps(settings)},
        )
        allowed = re.compile(r"^(\d{1,3}_(drill|mill)_[0-9.]{1,8}mm\.nc|preview\.svg|programs\.json)$")
        return read_zip(response.content, lambda name: bool(allowed.match(name)))

    def get_json(self, url: str, request_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._call("GET", url, request_id).json()
        return result


# --- helpers -----------------------------------------------------------------------------------------------


def _package_parts(packages: dict[str, bytes]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("packages", (f"{board_id}.zip", data, "application/zip")) for board_id, data in packages.items()]


def _problem(response: httpx.Response) -> tuple[str, str] | None:
    if not response.headers.get("content-type", "").startswith("application/problem+json"):
        return None
    try:
        body = response.json()
        return str(body["code"]), str(body["detail"])
    except (ValueError, KeyError, TypeError):
        return None


def read_zip(data: bytes, allowed: Callable[[str], bool]) -> dict[str, bytes]:
    """Files of a ZIP from another service. Only file names the contract allows are accepted."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES or sum(e.file_size for e in entries) > MAX_ZIP_BYTES:
                raise Unavailable("answer too large")
            if any(not allowed(e.filename) for e in entries):
                raise Unavailable("unexpected file in answer")
            return {e.filename: archive.read(e) for e in entries}
    except zipfile.BadZipFile as exc:
        raise Unavailable("answer is not a ZIP") from exc
