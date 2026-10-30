"""Job store: SQLite database plus one folder per job. Every job belongs to one account (``owner``).

The database is the queue. Workers claim jobs with an atomic update, so several worker processes (or threads) can
share one store without a separate broker.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


@dataclass
class JobRecord:
    id: str
    status: str
    created: float
    updated: float
    #: Unix time after which the job is deleted, 0 = never (jobs of accounts are kept until their owner deletes them).
    expires: float
    params: dict[str, Any]
    error: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    owner: str = ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    expires REAL NOT NULL,
    params TEXT NOT NULL,
    error TEXT,
    files TEXT NOT NULL DEFAULT '[]',
    client TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs (status, created);
CREATE INDEX IF NOT EXISTS jobs_client ON jobs (client, created);
CREATE INDEX IF NOT EXISTS jobs_expires ON jobs (expires);
"""
#: Created after the migration, because a database of an older version has no ``owner`` column yet.
_OWNER_INDEX = "CREATE INDEX IF NOT EXISTS jobs_owner ON jobs (owner, created)"


class JobStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)
            if "owner" not in {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}:
                # jobs of the anonymous time: nobody owns them, they expire and are deleted as before
                db.execute("ALTER TABLE jobs ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
            db.execute(_OWNER_INDEX)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.settings.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
        finally:
            db.close()

    def job_dir(self, job_id: str) -> Path:
        return self.settings.jobs_dir / job_id

    @staticmethod
    def _record(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            status=row["status"],
            created=row["created"],
            updated=row["updated"],
            expires=row["expires"],
            params=json.loads(row["params"]),
            error=row["error"],
            files=json.loads(row["files"]),
            owner=row["owner"],
        )

    def create(self, job_id: str, params: dict[str, Any], owner: str) -> JobRecord:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "INSERT INTO jobs (id, status, created, updated, expires, params, owner) VALUES (?,?,?,?,?,?,?)",
                (job_id, QUEUED, now, now, 0, json.dumps(params), owner),
            )
        return JobRecord(job_id, QUEUED, now, now, 0, params, owner=owner)

    def get(self, job_id: str, owner: str) -> JobRecord | None:
        """The job if it exists and belongs to ``owner``; the same answer for both cases, so ids stay private."""
        if not owner:
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ? AND owner = ?", (job_id, owner)).fetchone()
        return self._record(row) if row else None

    def list_for(self, owner: str, limit: int, offset: int) -> tuple[list[JobRecord], int]:
        """The newest jobs of ``owner`` first, and how many jobs the owner has."""
        if not owner:
            return [], 0
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE owner = ? ORDER BY created DESC, id LIMIT ? OFFSET ?", (owner, limit, offset)
            ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM jobs WHERE owner = ?", (owner,)).fetchone()[0]
        return [self._record(row) for row in rows], int(total)

    def count_for(self, owner: str) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM jobs WHERE owner = ?", (owner,)).fetchone()[0])

    def delete(self, job_id: str, owner: str) -> str:
        """Delete a job of ``owner`` with its files. Returns ``"deleted"``, ``"running"`` or ``"missing"``."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id = ? AND owner = ?", (job_id, owner)).fetchone()
            if row is None or not owner:
                db.execute("COMMIT")
                return "missing"
            if row["status"] == RUNNING:
                db.execute("COMMIT")
                return "running"
            db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            db.execute("COMMIT")
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
        return "deleted"

    def claim_next(self) -> JobRecord | None:
        """Take the oldest queued job and mark it as running (atomic)."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created LIMIT 1", (QUEUED,)).fetchone()
            if row is None:
                db.execute("COMMIT")
                return None
            db.execute("UPDATE jobs SET status = ?, updated = ? WHERE id = ?", (RUNNING, time.time(), row["id"]))
            db.execute("COMMIT")
        record = self._record(row)
        record.status = RUNNING
        return record

    def finish(self, job_id: str, files: list[dict[str, Any]], params: dict[str, Any] | None = None) -> None:
        """Mark the job as done. ``params`` replaces the stored ones when the workflow has completed them."""
        with self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = ?, updated = ?, files = ?, error = NULL WHERE id = ?",
                (DONE, time.time(), json.dumps(files), job_id),
            )
            if params is not None:
                db.execute("UPDATE jobs SET params = ? WHERE id = ?", (json.dumps(params), job_id))

    def fail(self, job_id: str, error: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = ?, updated = ?, error = ? WHERE id = ?",
                (FAILED, time.time(), error, job_id),
            )

    def requeue_stale(self, older_than_s: float) -> int:
        """Jobs left in ``running`` by a crashed worker go back to the queue."""
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status = ?, updated = ? WHERE status = ? AND updated < ?",
                (QUEUED, time.time(), RUNNING, time.time() - older_than_s),
            )
            return cursor.rowcount

    def queued_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (QUEUED,)).fetchone()[0])

    def recent_count(self, owner: str, window_s: float = 3600.0) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE owner = ? AND created > ?", (owner, time.time() - window_s)
            ).fetchone()
        return int(row[0])

    def delete_expired(self) -> int:
        """Remove expired jobs and their files (only jobs of the anonymous time expire). Returns how many."""
        with self._connect() as db:
            rows = db.execute("SELECT id FROM jobs WHERE expires > 0 AND expires <= ?", (time.time(),)).fetchall()
            for row in rows:
                shutil.rmtree(self.job_dir(row["id"]), ignore_errors=True)
            db.execute("DELETE FROM jobs WHERE expires > 0 AND expires <= ?", (time.time(),))
        return len(rows)
