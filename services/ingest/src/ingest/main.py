"""The ingest service: Gerber ZIP in, canonical board package out. No state."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import FastAPI, File, Form, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from . import common
from .common import Isolation, Problem
from .package import build_package

NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 10 * 1024 * 1024
    timeout_s: float = 60.0
    max_parallel: int = 4
    isolate: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            max_upload_bytes=common.env_int("MAX_UPLOAD_MB", 10) * 1024 * 1024,
            timeout_s=common.env_float("REQUEST_TIMEOUT_S", 60),
            max_parallel=common.env_int("MAX_PARALLEL", 4),
            isolate=os.environ.get("ISOLATE", "1") != "0",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    isolation = Isolation(settings.timeout_s, settings.max_parallel, settings.isolate)
    app = FastAPI(title="PCBHomeFab ingest", version="1.0.0")
    common.install(app, "ingest")
    app.state.isolation = isolation

    @app.post("/v1/packages")
    async def create_package(
        file: Annotated[UploadFile, File()],
        name: Annotated[str, Form()] = "board",
    ) -> Response:
        if not NAME.match(name):
            raise Problem(422, "common.invalid_request", "The name may have 1 to 40 characters of A-Z a-z 0-9 _ -.")
        data = await common.read_limited(file, settings.max_upload_bytes)
        package: bytes = await run_in_threadpool(isolation.run, build_package, data, name)
        return Response(
            package, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}.zip"'}
        )

    return app
