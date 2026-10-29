"""Worker: takes queued jobs and runs them. The heavy work happens in the other services, so threads are enough."""

from __future__ import annotations

import logging
import threading
import time
import traceback

from .config import Settings
from .services import INTERNAL_ERROR, Services, UserError
from .store import JobStore
from .workflow import run_job

log = logging.getLogger("jobs.worker")


def process_next(store: JobStore, services: Services) -> bool:
    """Run the oldest queued job. Returns ``False`` if the queue is empty."""
    job = store.claim_next()
    if job is None:
        return False
    try:
        files = run_job(store.job_dir(job.id), job.params, services)
    except UserError as exc:
        store.fail(job.id, exc.message)
    except Exception:
        log.error("Job failed:\n%s", traceback.format_exc())
        store.fail(job.id, INTERNAL_ERROR)
    else:
        store.finish(job.id, files, job.params)
    return True


def worker_loop(
    store: JobStore, settings: Settings, services: Services, stop: threading.Event, poll_s: float = 1.0
) -> None:
    """Process jobs until ``stop`` is set. Also cleans up expired jobs now and then."""
    store.requeue_stale(settings.job_timeout_s * 2)
    last_cleanup = 0.0
    while not stop.is_set():
        if time.monotonic() - last_cleanup > 600:
            store.delete_expired()
            last_cleanup = time.monotonic()
        try:
            worked = process_next(store, services)
        except Exception:
            log.error("Worker error:\n%s", traceback.format_exc())
            worked = False
        if not worked:
            stop.wait(poll_s)
