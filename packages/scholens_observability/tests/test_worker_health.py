from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from scholens_observability.worker_health import heartbeat, healthy


def test_missing_and_stale_worker_heartbeats_are_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "heartbeat"
    monkeypatch.setenv("SCHOLENS_WORKER_HEARTBEAT_FILE", str(path))
    assert not healthy()
    heartbeat()
    assert healthy()
    old = time.time() - 120
    os.utime(path, (old, old))
    assert not healthy()


def test_worker_health_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCHOLENS_WORKER_HEARTBEAT_FILE", raising=False)
    heartbeat(sender=object())
    assert not healthy()


def test_future_heartbeat_is_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "heartbeat"
    monkeypatch.setenv("SCHOLENS_WORKER_HEARTBEAT_FILE", str(path))
    heartbeat()
    future = time.time() + 120
    os.utime(path, (future, future))
    assert not healthy()
