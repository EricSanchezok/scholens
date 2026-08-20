from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess

from scholens_job_contracts import (
    JOB_QUEUE_NAMES,
    JOBS_WORKER_QUEUE_NAMES,
    JobQueue,
)

ROOT = Path(__file__).parents[2]


def _queue_expression(call: ast.Call) -> ast.expr | None:
    if not isinstance(call.func, ast.Name) or call.func.id not in {
        "EnqueueJob",
        "EnqueueJobCommand",
    }:
        return None
    return next(
        (keyword.value for keyword in call.keywords if keyword.arg == "queue"),
        None,
    )


def test_all_product_enqueue_sites_use_the_shared_queue_contract() -> None:
    seen: set[JobQueue] = set()
    for path in (ROOT / "server" / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            expression = _queue_expression(call)
            if expression is None:
                continue
            if (
                isinstance(expression, ast.Attribute)
                and isinstance(expression.value, ast.Name)
                and expression.value.id == "command"
                and expression.attr == "queue"
            ):
                continue
            assert isinstance(expression, ast.Attribute), (
                f"{path}:{call.lineno} must use JobQueue, not a local queue value"
            )
            assert isinstance(expression.value, ast.Name)
            assert expression.value.id == "JobQueue"
            queue = JobQueue[expression.attr]
            assert queue in JOB_QUEUE_NAMES
            seen.add(queue)

    assert seen == JOB_QUEUE_NAMES
    application_contract = (
        ROOT / "server" / "app" / "modules" / "jobs" / "application" / "jobs.py"
    ).read_text(encoding="utf-8")
    assert "queue: JobQueue" in application_contract


def test_jobs_routes_import_the_same_queue_enum() -> None:
    source = (ROOT / "jobs" / "src" / "celery_app.py").read_text(encoding="utf-8")

    assert "from scholens_job_contracts import JobQueue" in source
    for queue in JOBS_WORKER_QUEUE_NAMES:
        assert f"JobQueue.{queue.name}" in source
    assert "JobQueue.CONVERSATION" not in source
    assert '"pdf_processing"' not in source


def test_local_worker_command_resolves_queues_from_shared_contract(tmp_path) -> None:
    captured = tmp_path / "worker-args.txt"
    python = tmp_path / "python"
    python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "-m scholens_job_contracts" ]]; then
  printf '%s\\n' 'document,maintenance,research'
  exit 0
fi
printf '%s\\n' "$@" > "$CAPTURE_PATH"
""",
        encoding="utf-8",
    )
    python.chmod(0o755)
    environment = {
        **os.environ,
        "SCHOLENS_JOBS_PYTHON": str(python),
        "CAPTURE_PATH": str(captured),
    }

    subprocess.run(
        ["bash", str(ROOT / "jobs" / "scripts" / "start_worker.sh")],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    arguments = captured.read_text(encoding="utf-8").splitlines()
    assert "--queues=document,maintenance,research" in arguments
    assert not any(argument.startswith("--time-limit") for argument in arguments)
    assert not any(argument.startswith("--soft-time-limit") for argument in arguments)
