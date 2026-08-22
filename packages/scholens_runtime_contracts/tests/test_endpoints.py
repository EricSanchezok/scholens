from __future__ import annotations

import pytest

from scholens_runtime_contracts import (
    EndpointConfigurationError,
    resolve_cache_url,
    resolve_internal_callback_base_url,
    validate_database_endpoint,
)


def test_split_production_cache_is_canonical_and_escaped() -> None:
    assert resolve_cache_url(
        host="scholens.xxxxxx.0001.apse1.cache.amazonaws.com",
        port="6379",
        username="runtime user",
        password="secret/value",
        tls="true",
        environment="production",
    ) == (
        "rediss://runtime%20user:secret%2Fvalue@"
        "scholens.xxxxxx.0001.apse1.cache.amazonaws.com:6379/0"
    )


def test_direct_production_cache_uses_the_same_contract() -> None:
    assert resolve_cache_url(
        configured_url=(
            "rediss://runtime:secret%2Fvalue@"
            "scholens.xxxxxx.0001.apse1.cache.amazonaws.com:6380/0"
        ),
        environment="production",
    ) == (
        "rediss://runtime:secret%2Fvalue@"
        "scholens.xxxxxx.0001.apse1.cache.amazonaws.com:6380/0"
    )


def test_split_credentials_preserve_literal_percent_escape_text() -> None:
    assert resolve_cache_url(
        host="scholens.xxxxxx.0001.apse1.cache.amazonaws.com",
        port="6379",
        username="runtime%2Fuser",
        password="secret%2Fvalue",
        tls=True,
        environment="production",
    ) == (
        "rediss://runtime%252Fuser:secret%252Fvalue@"
        "scholens.xxxxxx.0001.apse1.cache.amazonaws.com:6379/0"
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tls": False}, "must use TLS"),
        ({"username": ""}, "CACHE_USERNAME is required"),
        ({"password": ""}, "CACHE_PASSWORD is required"),
        ({"host": "cache.example.com"}, "managed-service hostname"),
        ({"host": "cache.amazonaws.com@attacker.test"}, "structural character"),
        ({"host": "cache.amazonaws.com\r\nX: injected"}, "whitespace"),
        ({"port": "6379/path"}, "integer"),
    ],
)
def test_split_production_cache_rejects_unsafe_shapes(kwargs, message: str) -> None:
    values = {
        "host": "scholens.xxxxxx.0001.apse1.cache.amazonaws.com",
        "port": "6379",
        "username": "runtime",
        "password": "secret",
        "tls": True,
        "environment": "production",
    }
    values.update(kwargs)
    with pytest.raises(EndpointConfigurationError, match=message):
        resolve_cache_url(**values)


@pytest.mark.parametrize(
    "url",
    [
        "rediss://runtime:secret@cache.example.com:6379/0",
        "rediss://runtime:secret@scholens.cache.amazonaws.com:6379/0?x=y",
        "rediss://runtime:secret@scholens.cache.amazonaws.com:6379/0#fragment",
        "rediss://runtime:secret@scholens.cache.amazonaws.com:70000/0",
        "rediss://runtime:secret%0Ainjected@scholens.cache.amazonaws.com:6379/0",
    ],
)
def test_direct_production_cache_rejects_unsafe_shapes(url: str) -> None:
    with pytest.raises(EndpointConfigurationError):
        resolve_cache_url(configured_url=url, environment="production")


def test_production_database_requires_rds_dns_and_valid_port() -> None:
    assert validate_database_endpoint(
        host="scholens.abc.ap-southeast-1.rds.amazonaws.com",
        port="5432",
        environment="production",
    ) == ("scholens.abc.ap-southeast-1.rds.amazonaws.com", 5432)
    with pytest.raises(EndpointConfigurationError):
        validate_database_endpoint(
            host="db.example.com@attacker.test",
            port="5432?sslmode=disable",
            environment="production",
        )


def test_production_internal_callback_base_is_explicit_and_canonical() -> None:
    assert (
        resolve_internal_callback_base_url(
            configured_url="HTTP://Scholens-Api.Production.SVC.SanchezCloud:8000/",
            environment="production",
        )
        == "http://scholens-api.production.svc.sanchezcloud:8000"
    )


@pytest.mark.parametrize(
    "configured_url",
    [
        None,
        "http://127.0.0.1:7301",
        "http://[::1]:7301",
        "http://0.0.0.0:7301",
        "http://169.254.10.20:7301",
        "http://localhost:7301",
        "ftp://api.example.com",
        "http://user:secret@api.example.com",
        "http://api.example.com/internal/v1",
        "http://api.example.com?target=elsewhere",
        "http://api.example.com#fragment",
    ],
)
def test_production_internal_callback_base_rejects_unsafe_values(
    configured_url: str | None,
) -> None:
    with pytest.raises(EndpointConfigurationError):
        resolve_internal_callback_base_url(
            configured_url=configured_url,
            environment="production",
        )


def test_development_internal_callback_base_uses_loopback_fallback() -> None:
    assert (
        resolve_internal_callback_base_url(
            environment="development",
            fallback_url="http://127.0.0.1:7301",
        )
        == "http://127.0.0.1:7301"
    )
