"""HTTP basics every service needs: problem+json errors, request ids, health check, isolated requests.

This file is copied into each service on purpose (no shared code, see ADR-001). Keep the copies identical, only the
package name differs. The contract it implements is in ``contracts/README.md``.
"""

from __future__ import annotations

import contextvars
import logging
import multiprocessing
import os
import re
import threading
import traceback
import uuid
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from multiprocessing.connection import Connection
from typing import Any

from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("service")
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
INTERNAL_DETAIL = "Internal error while creating the files."


class Problem(Exception):  # noqa: N818 - named after the RFC 9457 "problem"
    """An error with a stable code. ``detail`` is safe to show to users."""

    def __init__(self, status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(status, code, detail, headers)  # keeps the exception picklable
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = headers


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def problem_response(status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "detail": detail,
        "request_id": request_id_var.get(),
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(service: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter(f"%(asctime)s %(levelname)s {service} [%(request_id)s] %(message)s"))
    root = logging.getLogger()
    if not any(isinstance(h.formatter, logging.Formatter) and service in str(h.formatter._fmt) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(logging.INFO)


def install(app: FastAPI, service: str) -> None:
    """Request ids, security headers, problem+json for every error and ``GET /healthz``."""
    configure_logging(service)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-Id"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @app.exception_handler(Problem)
    async def on_problem(_request: Request, exc: Problem) -> JSONResponse:
        return problem_response(exc.status, exc.code, exc.detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def on_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        return problem_response(422, "common.invalid_request", f"Invalid request ({where}: {first.get('msg', '')}).")

    @app.exception_handler(StarletteHTTPException)
    async def on_http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "common.not_found" if exc.status_code == 404 else "common.invalid_request"
        return problem_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def on_error(_request: Request, exc: Exception) -> JSONResponse:
        log.error("Unhandled error:\n%s", "".join(traceback.format_exception(exc)))
        return problem_response(500, "common.internal", INTERNAL_DETAIL)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}


async def read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read an uploaded part, refuse it with 413 when it is larger than ``limit`` bytes."""
    data = bytearray()
    while chunk := await upload.read(64 * 1024):
        data += chunk
        if len(data) > limit:
            raise Problem(413, "common.too_large", f"A file is larger than {limit // (1024 * 1024)} MB.")
    return bytes(data)


# --- one request, one process, one time limit --------------------------------------------------------------


def _child(connection: Connection, func: Callable[..., Any], args: tuple[Any, ...]) -> None:
    try:
        connection.send(("ok", func(*args)))
    except Problem as exc:
        connection.send(("problem", exc))
    except Exception:
        log.error("Request failed:\n%s", traceback.format_exc())
        connection.send(("error", None))
    finally:
        connection.close()


class Isolation:
    """Runs a function per request in its own process, with a time limit and a limit of parallel requests."""

    def __init__(self, timeout_s: float, max_parallel: int, enabled: bool = True) -> None:
        self.timeout_s = timeout_s
        self.enabled = enabled
        self._slots = threading.BoundedSemaphore(max_parallel)

    def run(self, func: Callable[..., Any], *args: Any) -> Any:
        """Result of ``func(*args)``. ``func`` and its arguments and result must be picklable."""
        if not self._slots.acquire(blocking=False):
            raise Problem(503, "common.busy", "The service is busy. Try again in a moment.", {"Retry-After": "5"})
        try:
            kind, value = self._run_isolated(func, args) if self.enabled else self._run_here(func, args)
        finally:
            self._slots.release()
        if kind == "ok":
            return value
        if kind == "problem":
            raise value
        raise Problem(500, "common.internal", INTERNAL_DETAIL)

    @staticmethod
    def _run_here(func: Callable[..., Any], args: tuple[Any, ...]) -> tuple[str, Any]:
        try:
            return "ok", func(*args)
        except Problem as exc:
            return "problem", exc
        except Exception:
            log.error("Request failed:\n%s", traceback.format_exc())
            return "error", None

    def _run_isolated(self, func: Callable[..., Any], args: tuple[Any, ...]) -> tuple[str, Any]:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_child, args=(sender, func, args), daemon=True)
        process.start()
        sender.close()
        try:
            if receiver.poll(self.timeout_s):
                try:
                    result: tuple[str, Any] = receiver.recv()
                except EOFError:
                    result = ("error", None)
            else:
                result = (
                    "problem",
                    Problem(503, "common.timeout", f"The request took longer than {self.timeout_s:g} seconds."),
                )
            process.join(5)
        finally:
            if process.is_alive():
                process.kill()
                process.join()
            receiver.close()
        return result
