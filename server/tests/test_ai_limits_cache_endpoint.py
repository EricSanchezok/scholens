from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.helpers import ai_limits


@pytest.mark.asyncio
@pytest.mark.parametrize("feature", ["chat", "research", "upload"])
async def test_product_limiters_create_redis_client_from_production_split_fields(
    monkeypatch: pytest.MonkeyPatch,
    feature: str,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CACHE_URL", raising=False)
    monkeypatch.setenv(
        "CACHE_HOST",
        "scholens.abc.0001.apse1.cache.amazonaws.com",
    )
    monkeypatch.setenv("CACHE_PORT", "6379")
    monkeypatch.setenv("CACHE_USERNAME", "api user")
    monkeypatch.setenv("CACHE_PASSWORD", "secret/value")
    monkeypatch.setenv("CACHE_TLS", "true")
    client = MagicMock()
    client.eval = AsyncMock(return_value=1)
    ai_limits._redis_clients.clear()

    with patch.object(ai_limits.Redis, "from_url", return_value=client) as from_url:
        await ai_limits.enforce_rate_limit(
            user_id=42,
            ip_address="203.0.113.10",
            feature=feature,
        )

    from_url.assert_called_once_with(
        "rediss://api%20user:secret%2Fvalue@"
        "scholens.abc.0001.apse1.cache.amazonaws.com:6379/0",
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
        retry_on_timeout=False,
    )
