"""Strict, deterministic validation for managed runtime endpoints."""

from __future__ import annotations

import re
from ipaddress import ip_address
from urllib.parse import quote, unquote, urlsplit

_DNS_NAME = re.compile(
    r"(?=.{1,253}\Z)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\Z"
)
_ELASTICACHE_SUFFIX = re.compile(r"(?:^|\.)cache\.amazonaws\.com(?:\.cn)?\Z")
_RDS_SUFFIX = re.compile(r"(?:^|\.)rds\.amazonaws\.com(?:\.cn)?\Z")
_STRUCTURAL_CHARACTERS = frozenset("@/?#\\\r\n")


class EndpointConfigurationError(ValueError):
    """A runtime endpoint cannot be represented safely or violates production policy."""


def _production(environment: str | None) -> bool:
    return (environment or "development").casefold() == "production"


def _reject_control_or_structure(value: str, *, field: str) -> None:
    if not value or any(character.isspace() for character in value):
        raise EndpointConfigurationError(
            f"{field} must be non-empty and contain no whitespace"
        )
    if any(character in value for character in _STRUCTURAL_CHARACTERS):
        raise EndpointConfigurationError(f"{field} contains a URL structural character")


def _port(value: int | str, *, field: str) -> int:
    if isinstance(value, bool):
        raise EndpointConfigurationError(f"{field} must be an integer from 1 to 65535")
    text = str(value)
    if not text.isascii() or not text.isdecimal():
        raise EndpointConfigurationError(f"{field} must be an integer from 1 to 65535")
    parsed = int(text)
    if not 1 <= parsed <= 65535:
        raise EndpointConfigurationError(f"{field} must be an integer from 1 to 65535")
    return parsed


def _host(value: str, *, field: str, managed_suffix: re.Pattern[str] | None) -> str:
    _reject_control_or_structure(value, field=field)
    canonical = value.casefold()
    if _DNS_NAME.fullmatch(canonical) is None:
        raise EndpointConfigurationError(f"{field} must be a valid DNS hostname")
    if managed_suffix is not None and managed_suffix.search(canonical) is None:
        raise EndpointConfigurationError(
            f"{field} must be an AWS managed-service hostname"
        )
    return canonical


def _credential(
    value: str | None,
    *,
    field: str,
    required: bool,
    url_encoded: bool,
) -> str:
    raw = value or ""
    credential = unquote(raw) if url_encoded else raw
    if any(character in credential for character in "\r\n"):
        raise EndpointConfigurationError(f"{field} must not contain CR or LF")
    if required and not credential:
        raise EndpointConfigurationError(f"{field} is required in production")
    return quote(credential, safe="")


def _tls_flag(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.casefold()
    if normalized not in {"true", "false"}:
        raise EndpointConfigurationError("CACHE_TLS must be true or false")
    return normalized == "true"


def resolve_cache_url(
    *,
    configured_url: str | None = None,
    host: str | None = None,
    port: int | str = 6379,
    username: str | None = None,
    password: str | None = None,
    tls: bool | str = False,
    environment: str | None = None,
    fallback_url: str | None = None,
) -> str | None:
    """Return one canonical Redis URL after validating direct or split inputs."""
    production = _production(environment)
    source_url = configured_url or (
        fallback_url if not production and not host else None
    )
    if source_url:
        if "\r" in source_url or "\n" in source_url:
            raise EndpointConfigurationError("CACHE_URL must not contain CR or LF")
        try:
            parsed = urlsplit(source_url)
            parsed_port = parsed.port
        except ValueError as exc:
            raise EndpointConfigurationError("CACHE_URL is malformed") from exc
        if parsed.scheme not in {"redis", "rediss"}:
            raise EndpointConfigurationError("CACHE_URL must use redis or rediss")
        if parsed.query or parsed.fragment:
            raise EndpointConfigurationError(
                "CACHE_URL must not contain query or fragment data"
            )
        if parsed.path not in {"", "/", "/0"}:
            raise EndpointConfigurationError("CACHE_URL must select database 0")
        if parsed.hostname is None or parsed_port is None:
            raise EndpointConfigurationError(
                "CACHE_URL must include a hostname and port"
            )
        cache_host = _host(
            parsed.hostname,
            field="CACHE_HOST",
            managed_suffix=_ELASTICACHE_SUFFIX if production else None,
        )
        cache_port = _port(parsed_port, field="CACHE_PORT")
        cache_username = _credential(
            parsed.username,
            field="CACHE_USERNAME",
            required=production,
            url_encoded=True,
        )
        cache_password = _credential(
            parsed.password,
            field="CACHE_PASSWORD",
            required=production,
            url_encoded=True,
        )
        cache_tls = parsed.scheme == "rediss"
    elif host:
        cache_host = _host(
            host,
            field="CACHE_HOST",
            managed_suffix=_ELASTICACHE_SUFFIX if production else None,
        )
        cache_port = _port(port, field="CACHE_PORT")
        cache_username = _credential(
            username,
            field="CACHE_USERNAME",
            required=production,
            url_encoded=False,
        )
        cache_password = _credential(
            password,
            field="CACHE_PASSWORD",
            required=production,
            url_encoded=False,
        )
        cache_tls = _tls_flag(tls)
    elif production:
        raise EndpointConfigurationError(
            "CACHE configuration is required in production"
        )
    else:
        return None

    if production and not cache_tls:
        raise EndpointConfigurationError("production cache must use TLS")
    credentials = ""
    if cache_username or cache_password:
        credentials = f"{cache_username}:{cache_password}@"
    scheme = "rediss" if cache_tls else "redis"
    return f"{scheme}://{credentials}{cache_host}:{cache_port}/0"


def validate_database_endpoint(
    *,
    host: str,
    port: int | str,
    environment: str | None = None,
) -> tuple[str, int]:
    """Validate a PostgreSQL host/port pair before interpolating a URL."""
    production = _production(environment)
    return (
        _host(
            host,
            field="DATABASE_HOST",
            managed_suffix=_RDS_SUFFIX if production else None,
        ),
        _port(port, field="DATABASE_PORT"),
    )


def resolve_internal_callback_base_url(
    *,
    configured_url: str | None = None,
    environment: str | None = None,
    fallback_url: str | None = None,
) -> str:
    """Return a canonical Server callback base URL for internal Jobs requests.

    Production must provide an explicit, non-loopback HTTP endpoint. Development
    may use the documented loopback fallback, but configured values still pass
    the same structural validation so task payloads cannot smuggle credentials,
    query parameters, or fragments into the callback authority.
    """
    production = _production(environment)
    source_url = configured_url or (fallback_url if not production else None)
    if not source_url:
        raise EndpointConfigurationError(
            "WEBHOOK_BASE_URL is required in production"
            if production
            else "WEBHOOK_BASE_URL is required"
        )
    if any(character.isspace() for character in source_url):
        raise EndpointConfigurationError("WEBHOOK_BASE_URL must contain no whitespace")
    try:
        parsed = urlsplit(source_url)
        parsed_port = parsed.port
    except ValueError as exc:
        raise EndpointConfigurationError("WEBHOOK_BASE_URL is malformed") from exc
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise EndpointConfigurationError("WEBHOOK_BASE_URL must use http or https")
    if parsed.hostname is None:
        raise EndpointConfigurationError("WEBHOOK_BASE_URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise EndpointConfigurationError(
            "WEBHOOK_BASE_URL must not include credentials"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise EndpointConfigurationError(
            "WEBHOOK_BASE_URL must not include path, query, or fragment data"
        )
    hostname = parsed.hostname.casefold().rstrip(".")
    if production:
        loopback = hostname == "localhost" or hostname.endswith(".localhost")
        try:
            address = ip_address(hostname)
            loopback = loopback or any(
                (
                    address.is_loopback,
                    address.is_unspecified,
                    address.is_link_local,
                    address.is_multicast,
                )
            )
        except ValueError:
            pass
        if loopback:
            raise EndpointConfigurationError(
                "production WEBHOOK_BASE_URL must use a routable, non-loopback host"
            )
    port = f":{parsed_port}" if parsed_port is not None else ""
    bracketed_host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{parsed.scheme.casefold()}://{bracketed_host}{port}"
