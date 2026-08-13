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
    collector = _collector.get()
    if collector is None:
        return

    status = "unknown" if usage is None else "settled"
    prompt_tokens = int(
        getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", 0)) or 0
    )
    completion_tokens = int(
        getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0))
        or 0
    )
    total_tokens = int(
        getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0
    )
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)

    collector.events.append(
        {
            "idempotency_key": (f"jobs:{collector.operation_id}:{idempotency_suffix}"),
            "operation_id": collector.operation_id,
            "feature": feature,
            "provider": profile.provider,
            "model": profile.model_id,
            "ai_profile": profile.name.value,
            "thinking": profile.thinking.value,
            "thinking_effort": profile.thinking_effort.value,
            "profile_revision": profile.revision,
            "provider_request_id": request_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": int(
                getattr(completion_details, "reasoning_tokens", 0)
                or getattr(usage, "details", {}).get("reasoning_tokens", 0)
            ),
            "cache_hit_tokens": int(
                getattr(usage, "cache_read_tokens", 0)
                or getattr(prompt_details, "cached_tokens", 0)
                or 0
            ),
            "cache_miss_tokens": 0,
            "total_tokens": total_tokens,
            "status": status,
        }
    )
