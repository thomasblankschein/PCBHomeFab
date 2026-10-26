"""Worker: takes queued jobs and runs them, each in its own process with a time limit."""

from __future__ import annotations

import logging
import multiprocessing
import threading
import time
import traceback
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from ..errors import PCBHomeFabError
from .config import Settings
from .runner import run_job
from .store import JobStore

log = logging.getLogger("pcbhomefab.worker")
INTERNAL_ERROR = "Internal error while creating the files."


def _run_safely(job_dir: Path, params: dict[str, Any]) -> tuple[str, Any]:
    """Result as ``("ok", files)`` or ``("error", message)``. Only library errors have user-safe messages."""
    try:
        return "ok", run_job(job_dir, params)
    except PCBHomeFabError as exc:
        return "error", str(exc)
    except Exception:
        log.error("Job failed:\n%s", traceback.format_exc())
        return "error", INTERNAL_ERROR


def _child(job_dir: Path, params: dict[str, Any], connection: Connection) -> None:
    connection.send(_run_safely(job_dir, params))
    connection.close()


def _run_isolated(job_dir: Path, params: dict[str, Any], timeout_s: float) -> tuple[str, Any]:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(job_dir, params, sender))
    process.start()
    sender.close()
    if receiver.poll(timeout_s):
        try:
            result: tuple[str, Any] = receiver.recv()
        except EOFError:
            result = ("error", INTERNAL_ERROR)
        process.join(5)
    else:
        result = ("error", f"The job took longer than {timeout_s:g} seconds and was stopped.")
    if process.is_alive():
        process.kill()
        process.join()
    receiver.close()
    return result


def process_next(store: JobStore, settings: Settings, isolated: bool = True) -> bool:
    """Run the oldest queued job. Returns ``False`` if the queue is empty."""
    job = store.claim_next()
    if job is None:
        return False
    job_dir = store.job_dir(job.id)
    if isolated:
        kind, value = _run_isolated(job_dir, job.params, settings.job_timeout_s)
    else:
        kind, value = _run_safely(job_dir, job.params)
    if kind == "ok":
        store.finish(job.id, value)
    else:
        store.fail(job.id, value)
    return True


def worker_loop(store: JobStore, settings: Settings, stop: threading.Event, poll_s: float = 1.0) -> None:
    """Process jobs until ``stop`` is set. Also cleans up expired jobs now and then."""
    store.requeue_stale(settings.job_timeout_s * 2)
    last_cleanup = 0.0
    while not stop.is_set():
        if time.monotonic() - last_cleanup > 600:
            store.delete_expired()
            last_cleanup = time.monotonic()
        try:
            worked = process_next(store, settings)
        except Exception:
            log.error("Worker error:\n%s", traceback.format_exc())
            worked = False
        if not worked:
            stop.wait(poll_s)
