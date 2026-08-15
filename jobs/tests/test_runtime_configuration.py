from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.cache_config import CacheConfigurationError, cache_url
from src.task_protection import set_task_protection


def test_managed_cache_url_escapes_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CACHE_URL", raising=False)
    monkeypatch.setenv("CACHE_HOST", "cache.example.invalid")
    monkeypatch.setenv("CACHE_USERNAME", "jobs user")
    monkeypatch.setenv("CACHE_PASSWORD", "secret/value")
    monkeypatch.setenv("CACHE_TLS", "true")

    assert cache_url() == (
        "rediss://jobs%20user:secret%2Fvalue@cache.example.invalid:6379/0"
    )


def test_production_cache_must_use_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(
        "CACHE_URL",
        "redis://jobs:secret@scholens.abc.cache.amazonaws.com:6379/0",
    )

    with pytest.raises(CacheConfigurationError, match="must use TLS"):
        cache_url()


def test_production_cache_requires_managed_host_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CACHE_URL", raising=False)
    monkeypatch.setenv(
        "CACHE_HOST",
        "scholens.abc.0001.apse1.cache.amazonaws.com",
    )
    monkeypatch.setenv("CACHE_PORT", "6379")
    monkeypatch.setenv("CACHE_USERNAME", "jobs")
    monkeypatch.setenv("CACHE_PASSWORD", "secret")
    monkeypatch.setenv("CACHE_TLS", "true")

    assert cache_url() == (
        "rediss://jobs:secret@scholens.abc.0001.apse1.cache.amazonaws.com:6379/0"
    )

    monkeypatch.setenv("CACHE_HOST", "cache.example.invalid")
    with pytest.raises(CacheConfigurationError, match="managed-service hostname"):
        cache_url()


def test_ecs_task_protection_uses_agent_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECS_AGENT_URI", "http://169.254.170.2/api")
    response = MagicMock()
    with patch("src.task_protection.requests.put", return_value=response) as put:
        set_task_protection(enabled=True, task_id="job-1")

    put.assert_called_once_with(
        "http://169.254.170.2/api/task-protection/v1/state",
        json={"ProtectionEnabled": True, "ExpiresInMinutes": 60},
        timeout=3,
    )
    response.raise_for_status.assert_called_once_with()
