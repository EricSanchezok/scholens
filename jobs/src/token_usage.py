"""Per-task AI provider usage collection for server-side settlement."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from scholens_ai import AIProfile


@dataclass
class UsageCollector:
    operation_id: str
    events: list[dict[str, Any]] = field(default_factory=list)


_collector: ContextVar[UsageCollector | None] = ContextVar(
    "jobs_token_usage_collector", default=None
)


@contextmanager
def collect_token_usage(operation_id: str) -> Iterator[UsageCollector]:
    collector = UsageCollector(operation_id=operation_id)
    token = _collector.set(collector)
    try:
        yield collector
    finally:
        _collector.reset(token)


def record_token_usage(
    *,
    feature: str,
    profile: AIProfile,
    usage: Any,
    request_id: str | None,
    idempotency_suffix: str,
) -> None:
    return
