"""Opt-in local worker heartbeat; no broker probes or provider calls."""

from __future__ import annotations

import os
import time
from pathlib import Path


def heartbeat(**_kwargs: object) -> None:
    """Record Celery readiness/heartbeat signals only for configured workers."""
    filename = os.getenv("SCHOLENS_WORKER_HEARTBEAT_FILE")
    if filename:
        Path(filename).touch()


def healthy() -> bool:
    """Fail closed if the worker has not refreshed its marker for 90 seconds."""
    filename = os.getenv("SCHOLENS_WORKER_HEARTBEAT_FILE")
    if not filename:
        return False
    try:
        age = time.time() - Path(filename).stat().st_mtime
    except OSError:
        return False
    return 0 <= age < 90


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
