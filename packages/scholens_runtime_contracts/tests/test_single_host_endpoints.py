"""The single-host deployment retains production endpoint safety checks."""

import pytest

from scholens_runtime_contracts import (
    EndpointConfigurationError,
    resolve_cache_url,
    validate_database_endpoint,
)


def test_single_host_database_requires_explicit_deployment_mode() -> None:
    host = "postgres.personal.svc.sanchezcloud"
    with pytest.raises(EndpointConfigurationError):
        validate_database_endpoint(host=host, port=5432, environment="production")
    assert validate_database_endpoint(
        host=host,
        port=5432,
        environment="production",
        deployment_mode="single-host",
    ) == (host, 5432)


def test_single_host_cache_retains_credentials_and_tls() -> None:
    assert (
        resolve_cache_url(
            host="cache.personal.svc.sanchezcloud",
            port=6380,
            username="api",
            password="private/value",
            tls=True,
            environment="production",
            deployment_mode="single-host",
        )
        == "rediss://api:private%2Fvalue@cache.personal.svc.sanchezcloud:6380/0"
    )


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "database.example.com",
        "personal.svc.sanchezcloud.evil.com",
    ],
)
def test_single_host_does_not_allow_arbitrary_database_hosts(host: str) -> None:
    with pytest.raises(EndpointConfigurationError):
        validate_database_endpoint(
            host=host,
            port=5432,
            environment="production",
            deployment_mode="single-host",
        )


@pytest.mark.parametrize(
    "url",
    [
        "redis://api:password@cache.personal.svc.sanchezcloud:6380/0",
        "rediss://cache.personal.svc.sanchezcloud:6380/0",
        "rediss://api:password@cache.example.com:6380/0",
    ],
)
def test_single_host_cache_rejects_unsafe_direct_urls(url: str) -> None:
    with pytest.raises(EndpointConfigurationError):
        resolve_cache_url(
            configured_url=url, environment="production", deployment_mode="single-host"
        )


def test_unknown_deployment_mode_fails_closed() -> None:
    with pytest.raises(EndpointConfigurationError, match="deployment mode"):
        validate_database_endpoint(
            host="db.rds.amazonaws.com",
            port=5432,
            environment="production",
            deployment_mode="typo",
        )
