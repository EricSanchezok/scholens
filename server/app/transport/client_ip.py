"""Bounded transport-edge normalization for ephemeral client IP values."""

from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_address

from starlette.requests import Request
from starlette.types import Scope

UNKNOWN_CLIENT_IP = "unknown"
MAX_CLIENT_IP_LENGTH = 64


def normalize_client_ip(value: object | None) -> str:
    """Return one canonical IP scalar without preserving arbitrary peer input."""
    if not isinstance(value, str):
        return UNKNOWN_CLIENT_IP
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_CLIENT_IP_LENGTH:
        return UNKNOWN_CLIENT_IP
    try:
        normalized = str(ip_address(candidate))
    except ValueError:
        return UNKNOWN_CLIENT_IP
    if len(normalized) > MAX_CLIENT_IP_LENGTH:
        return UNKNOWN_CLIENT_IP
    return normalized


def http_client_ip(request: Request) -> str:
    """Return the transport middleware's one canonical client-IP decision."""
    resolved = getattr(request.state, "client_ip", None)
    if isinstance(resolved, str):
        return normalize_client_ip(resolved)
    settings = getattr(request.app.state, "settings", None)
    return resolve_scope_client_ip(
        request.scope,
        environment=str(getattr(settings, "environment", "development")),
        trust_cloudflare=bool(getattr(settings, "trust_cloudflare_client_ip", False)),
        trusted_proxy_cidr=getattr(settings, "trusted_proxy_cidr", None),
    )


def resolve_scope_client_ip(
    scope: Scope,
    *,
    environment: str,
    trust_cloudflare: bool,
    trusted_proxy_cidr: IPv4Network | IPv6Network | None,
) -> str:
    """Resolve Cloudflare's canonical header only inside the production trust boundary."""
    client = scope.get("client")
    peer = normalize_client_ip(client[0] if client else None)
    if environment.casefold() != "production" or not trust_cloudflare:
        return peer
    try:
        peer_address = ip_address(peer)
    except ValueError:
        return UNKNOWN_CLIENT_IP
    if trusted_proxy_cidr is None or peer_address not in trusted_proxy_cidr:
        return peer

    values: list[str] = []
    for name, raw_value in scope.get("headers", []):
        if name.lower() != b"cf-connecting-ip":
            continue
        try:
            values.append(raw_value.decode("ascii"))
        except UnicodeDecodeError:
            return UNKNOWN_CLIENT_IP
    if len(values) != 1:
        return UNKNOWN_CLIENT_IP
    value = values[0]
    if (
        value != value.strip()
        or "," in value
        or any(character in value for character in "\r\n")
    ):
        return UNKNOWN_CLIENT_IP
    return normalize_client_ip(value)


def apply_trusted_proxy_scheme(
    scope: Scope,
    *,
    environment: str,
    trust_cloudflare: bool,
    trusted_proxy_cidr: IPv4Network | IPv6Network | None,
) -> None:
    """Apply Cloudflare's HTTPS scheme only after the same client-IP boundary passes."""
    if (
        resolve_scope_client_ip(
            scope,
            environment=environment,
            trust_cloudflare=trust_cloudflare,
            trusted_proxy_cidr=trusted_proxy_cidr,
        )
        == UNKNOWN_CLIENT_IP
    ):
        return
    client = scope.get("client")
    try:
        peer = ip_address(client[0] if client else "")
    except ValueError:
        return
    if (
        environment.casefold() != "production"
        or not trust_cloudflare
        or trusted_proxy_cidr is None
        or peer not in trusted_proxy_cidr
    ):
        return
    values = [
        raw_value
        for name, raw_value in scope.get("headers", [])
        if name.lower() == b"x-forwarded-proto"
    ]
    if len(values) == 1 and values[0] == b"https":
        scope["scheme"] = "https"


__all__ = [
    "MAX_CLIENT_IP_LENGTH",
    "UNKNOWN_CLIENT_IP",
    "apply_trusted_proxy_scheme",
    "http_client_ip",
    "normalize_client_ip",
    "resolve_scope_client_ip",
]
