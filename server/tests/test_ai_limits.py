from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from redis.exceptions import RedisError

from app.helpers import ai_limits
from app.helpers.ai_limits import AILimitExceeded, ai_limit_app_error
from app.shared.domain import FailureKind


def test_ai_limit_maps_real_quota_exhaustion_to_rate_limited() -> None:
    error = ai_limit_app_error(
        AILimitExceeded("rate_limit_exceeded"),
        exceeded_message="AI request limit exceeded",
    )

    assert error.code == "rate_limit_exceeded"
    assert error.message == "AI request limit exceeded"
    assert error.kind is FailureKind.RATE_LIMITED


def test_ai_limit_maps_redis_outage_to_unavailable() -> None:
    error = ai_limit_app_error(
        AILimitExceeded("concurrency_limit_unavailable"),
        exceeded_message="AI request limit exceeded",
    )

    assert error.code == "concurrency_limit_unavailable"
    assert error.message == "AI capacity checks are temporarily unavailable"
    assert error.kind is FailureKind.UNAVAILABLE


@pytest.mark.asyncio
async def test_rate_limit_uses_two_cluster_safe_single_key_scripts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    client.eval.side_effect = [4, 7]
    monkeypatch.setattr(ai_limits, "_redis_client", lambda _url=None: client)
    monkeypatch.setattr(ai_limits.time, "time", lambda: 1_725_000_012)
    monkeypatch.setenv("AI_RATE_WINDOW_SECONDS", "60")

    await ai_limits.enforce_rate_limit(
        user_id=42,
        ip_address="203.0.113.10",
        feature="chat",
    )

    window = 1_725_000_012 // 60
    assert client.eval.await_args_list == [
        call(
            ai_limits._RATE_LIMIT_SCRIPT,
            1,
            f"scholens:rate:user:42:chat:{window}",
            61,
        ),
        call(
            ai_limits._RATE_LIMIT_SCRIPT,
            1,
            f"scholens:rate:ip:203.0.113.10:chat:{window}",
            61,
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("counts", "user_limit", "ip_limit"),
    [([3, 1], 2, 10), ([1, 5], 10, 4)],
)
async def test_rate_limit_rejects_either_exceeded_counter(
    monkeypatch: pytest.MonkeyPatch,
    counts: list[int],
    user_limit: int,
    ip_limit: int,
) -> None:
    client = AsyncMock()
    client.eval.side_effect = counts
    monkeypatch.setattr(ai_limits, "_redis_client", lambda _url=None: client)
    monkeypatch.setenv("AI_RATE_PER_USER", str(user_limit))
    monkeypatch.setenv("AI_RATE_PER_IP", str(ip_limit))

    with pytest.raises(AILimitExceeded, match="rate_limit_exceeded"):
        await ai_limits.enforce_rate_limit(
            user_id=42,
            ip_address="203.0.113.10",
            feature="upload",
        )

    assert client.eval.await_count == 2


@pytest.mark.asyncio
async def test_rate_limit_maps_partial_redis_failure_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    client.eval.side_effect = [1, RedisError("cache unavailable")]
    metric = MagicMock()
    monkeypatch.setattr(ai_limits, "_redis_client", lambda _url=None: client)
    monkeypatch.setattr(ai_limits, "add_counter", metric)

    with pytest.raises(AILimitExceeded, match="rate_limit_unavailable"):
        await ai_limits.enforce_rate_limit(
            user_id=42,
            ip_address="203.0.113.10",
            feature="research",
        )

    metric.assert_called_once_with(
        "scholens.dependency.failures",
        attributes={"dependency": "redis"},
    )
