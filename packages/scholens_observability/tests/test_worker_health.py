from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scholens_observability.worker_health import heartbeat, healthy


@pytest.mark.parametrize("age,expected", [(None, 1), (0, 0), (120, 1), (-120, 1)])
def test_health_command_needs_no_telemetry_stack(tmp_path, age, expected):
    path = tmp_path / "heartbeat"
    if age is not None:
        path.touch()
        timestamp = time.time() - age
        os.utime(path, (timestamp, timestamp))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import runpy
import sys

class NoTelemetry(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'opentelemetry', 'boto3', 'botocore', 'httpx', 'pydantic'}:
            raise AssertionError(f'Health probe imported {fullname}')

sys.meta_path.insert(0, NoTelemetry())
runpy.run_module('scholens_observability.worker_health', run_name='__main__')
""",
        ],
        env={**os.environ, "SCHOLENS_WORKER_HEARTBEAT_FILE": str(path)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == expected, result.stderr
    assert not result.stderr


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
