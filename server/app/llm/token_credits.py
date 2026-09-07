from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Iterator

from app.database.models import TokenWeeklyUsage
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class UsageContext:
    user_id: int
    feature: str
    operation_id: str


_usage_context: ContextVar[UsageContext | None] = ContextVar(
    "scholens_llm_usage_context", default=None
)


def utc_week_start(now: datetime | None = None) -> date:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return (current - timedelta(days=current.weekday())).date()


@contextmanager
def llm_usage_context(
    *, user_id: int, feature: str, operation_id: str | None = None
) -> Iterator[UsageContext]:
    context = UsageContext(
        user_id=user_id,
        feature=feature,
        operation_id=operation_id or str(uuid.uuid4()),
    )
    token = _usage_context.set(context)
    try:
        yield context
    finally:
        _usage_context.reset(token)


def current_usage_context() -> UsageContext | None:
    return _usage_context.get()


def settle_token_usage(
    *,
    provider: str,
    model: str,
    ai_profile: str,
    thinking: str,
    thinking_effort: str,
    profile_revision: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    provider_request_id: str | None,
    reasoning_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    idempotency_key: str | None = None,
    status: str = "settled",
) -> bool:
    """Accept legacy settlement calls without recording BYOK usage."""
    return False


def get_token_usage(db: Session, *, user_id: int) -> int:
    value = db.scalar(
        select(TokenWeeklyUsage.used_tokens).where(
            TokenWeeklyUsage.user_id == user_id,
            TokenWeeklyUsage.week_start == utc_week_start(),
        )
    )
    return int(value or 0)


__all__ = [
    "UsageContext",
    "current_usage_context",
    "get_token_usage",
    "llm_usage_context",
    "settle_token_usage",
    "utc_week_start",
]
