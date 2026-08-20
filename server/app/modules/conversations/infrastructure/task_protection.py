"""Protect an ECS conversation worker while it owns a generation."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests
from celery import signals

logger = logging.getLogger(__name__)


def set_task_protection(*, enabled: bool, task_id: str | None = None) -> None:
    agent_uri = os.getenv("ECS_AGENT_URI")
    if not agent_uri:
        return
    try:
        response = requests.put(
            f"{agent_uri.rstrip('/')}/task-protection/v1/state",
            json={
                "ProtectionEnabled": enabled,
                **({"ExpiresInMinutes": 60} if enabled else {}),
            },
            timeout=3,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.warning(
            "conversation.ecs_task_protection.update_failed",
            exc_info=True,
            extra={"enabled": enabled, "task_id": task_id},
        )


def register_task_protection_signals() -> None:
    def protect_task(*, task_id: str | None = None, **_kwargs: Any) -> None:
        set_task_protection(enabled=True, task_id=task_id)

    def unprotect_task(*, task_id: str | None = None, **_kwargs: Any) -> None:
        set_task_protection(enabled=False, task_id=task_id)

    signals.task_prerun.connect(protect_task, weak=False)
    signals.task_postrun.connect(unprotect_task, weak=False)


__all__ = ["register_task_protection_signals"]
