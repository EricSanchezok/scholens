"""Resolve the managed cache endpoint without storing a composed secret."""

from __future__ import annotations

import os

from scholens_runtime_contracts import EndpointConfigurationError, resolve_cache_url


class CacheConfigurationError(RuntimeError):
    """The Jobs cache endpoint is missing or unsafe."""


def cache_url() -> str:
    try:
        url = resolve_cache_url(
            configured_url=os.getenv("CACHE_URL"),
            host=os.getenv("CACHE_HOST"),
            port=os.getenv("CACHE_PORT", "6379"),
            username=os.getenv("CACHE_USERNAME"),
            password=os.getenv("CACHE_PASSWORD"),
            tls=os.getenv("CACHE_TLS", "false"),
            environment=os.getenv("ENVIRONMENT", "development"),
            fallback_url="redis://127.0.0.1:56379/0",
        )
    except EndpointConfigurationError as exc:
        raise CacheConfigurationError(str(exc)) from exc
    if url is None:
        raise CacheConfigurationError("CACHE configuration is required")
    return url
