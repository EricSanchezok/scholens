"""The single Server composition boundary for cache endpoint resolution."""

from __future__ import annotations

import os

from scholens_runtime_contracts import resolve_cache_url


def cache_url_from_fields(
    *,
    configured_url: str | None,
    host: str | None,
    port: int | str,
    username: str | None,
    password: str | None,
    tls: bool | str,
    environment: str | None,
) -> str | None:
    """Resolve explicit settings fields using the shared runtime contract."""
    return resolve_cache_url(
        configured_url=configured_url,
        host=host,
        port=port,
        username=username,
        password=password,
        tls=tls,
        environment=environment,
    )


def cache_url_from_environment(
    *,
    explicit_url: str | None = None,
    environment: str | None = None,
) -> str | None:
    """Resolve an optional call-site override or the ECS-injected environment."""
    return cache_url_from_fields(
        configured_url=explicit_url or os.getenv("CACHE_URL"),
        host=None if explicit_url else os.getenv("CACHE_HOST"),
        port=os.getenv("CACHE_PORT", "6379"),
        username=os.getenv("CACHE_USERNAME"),
        password=os.getenv("CACHE_PASSWORD"),
        tls=os.getenv("CACHE_TLS", "false"),
        environment=environment or os.getenv("ENVIRONMENT", "development"),
    )
