"""Service settings, read from environment variables (all optional)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .common import env_float, env_int


@dataclass(frozen=True)
class Settings:
    """Limits, paths and the addresses of the other services. Every user is anonymous, the limits protect us."""

    #: Folder with the job database and one sub folder per job.
    data_dir: Path = Path("data")
    ingest_url: str = "http://ingest:8000"
    panel_url: str = "http://panel:8000"
    exposure_url: str = "http://exposure:8000"
    mill_url: str = "http://mill:8000"
    #: Largest accepted Gerber ZIP in bytes.
    max_upload_bytes: int = 10 * 1024 * 1024
    #: Number of different boards (ZIP files) per job.
    max_files: int = 8
    #: Number of boards on the plate, copies included.
    max_boards: int = 200
    #: Jobs and their files are deleted after this time.
    job_ttl_s: float = 7 * 24 * 3600
    #: A job that runs longer is stopped between two steps and marked as failed.
    job_timeout_s: float = 300.0
    #: Time limit for one call to another service (their own limits are lower).
    call_timeout_s: float = 150.0
    #: Jobs one client may create per hour.
    rate_limit_per_hour: int = 30
    #: Board and layout previews one client may ask for per hour (they cost a call to ingest or panel).
    preview_limit_per_hour: int = 300
    #: Jobs waiting in the queue, a new job is refused above this number.
    max_queued: int = 100
    #: Worker threads that run jobs.
    workers: int = 2
    #: Take the client address from ``X-Forwarded-For`` (only behind a trusted gateway).
    trust_proxy: bool = False
    #: Secret used to hash client addresses before they are stored.
    ip_salt: str = "change-me"
    #: Path prefix under which the gateway publishes this service (for the API documentation).
    root_path: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "data")),
            ingest_url=os.environ.get("INGEST_URL", cls.ingest_url).rstrip("/"),
            panel_url=os.environ.get("PANEL_URL", cls.panel_url).rstrip("/"),
            exposure_url=os.environ.get("EXPOSURE_URL", cls.exposure_url).rstrip("/"),
            mill_url=os.environ.get("MILL_URL", cls.mill_url).rstrip("/"),
            max_upload_bytes=env_int("MAX_UPLOAD_MB", 10) * 1024 * 1024,
            max_files=env_int("MAX_FILES", 8),
            max_boards=env_int("MAX_BOARDS", 200),
            job_ttl_s=env_float("JOB_TTL_HOURS", 168) * 3600,
            job_timeout_s=env_float("JOB_TIMEOUT_S", 300),
            call_timeout_s=env_float("CALL_TIMEOUT_S", 150),
            rate_limit_per_hour=env_int("RATE_LIMIT_PER_HOUR", 30),
            preview_limit_per_hour=env_int("PREVIEW_LIMIT_PER_HOUR", 300),
            max_queued=env_int("MAX_QUEUED", 100),
            workers=env_int("WORKERS", 2),
            trust_proxy=os.environ.get("TRUST_PROXY", "") == "1",
            ip_salt=os.environ.get("IP_SALT", "change-me"),
            root_path=os.environ.get("ROOT_PATH", ""),
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.sqlite3"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"
