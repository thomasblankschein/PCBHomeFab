"""Service settings, read from environment variables (all optional)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    """Limits and paths. Every user is anonymous, so the limits are the protection of the service."""

    #: Folder with the job database and one sub folder per job.
    data_dir: Path = Path("data")
    #: Largest accepted Gerber ZIP in bytes.
    max_upload_bytes: int = 10 * 1024 * 1024
    #: Number of different boards (ZIP files) per job.
    max_files: int = 8
    #: Number of boards on the plate, copies included.
    max_boards: int = 200
    #: Jobs and their files are deleted after this time.
    job_ttl_s: float = 7 * 24 * 3600
    #: A job that runs longer is stopped and marked as failed.
    job_timeout_s: float = 120.0
    #: Jobs one client may create per hour.
    rate_limit_per_hour: int = 30
    #: Jobs waiting in the queue, a new job is refused above this number.
    max_queued: int = 100
    #: Worker threads inside the web process (0 = use separate ``pcbhomefab worker`` processes).
    embedded_workers: int = 1
    #: Take the client address from ``X-Forwarded-For`` (only behind a trusted reverse proxy).
    trust_proxy: bool = False
    #: Secret used to hash client addresses before they are stored.
    ip_salt: str = "change-me"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.environ.get("PCBHOMEFAB_DATA_DIR", "data")),
            max_upload_bytes=_int("PCBHOMEFAB_MAX_UPLOAD_MB", 10) * 1024 * 1024,
            max_files=_int("PCBHOMEFAB_MAX_FILES", 8),
            max_boards=_int("PCBHOMEFAB_MAX_BOARDS", 200),
            job_ttl_s=_float("PCBHOMEFAB_JOB_TTL_HOURS", 168) * 3600,
            job_timeout_s=_float("PCBHOMEFAB_JOB_TIMEOUT_S", 120),
            rate_limit_per_hour=_int("PCBHOMEFAB_RATE_LIMIT_PER_HOUR", 30),
            max_queued=_int("PCBHOMEFAB_MAX_QUEUED", 100),
            embedded_workers=_int("PCBHOMEFAB_EMBEDDED_WORKERS", 1),
            trust_proxy=os.environ.get("PCBHOMEFAB_TRUST_PROXY", "") == "1",
            ip_salt=os.environ.get("PCBHOMEFAB_IP_SALT", "change-me"),
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.sqlite3"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"
