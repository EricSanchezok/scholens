from __future__ import annotations

import asyncio
from ipaddress import ip_network
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.transport.http.observability import RequestObservabilityMiddleware
from app.transport.client_ip import (
    MAX_CLIENT_IP_LENGTH,
    UNKNOWN_CLIENT_IP,
    apply_trusted_proxy_scheme,
    normalize_client_ip,
    resolve_scope_client_ip,
)

ROOT = Path(__file__).parents[2]
APP_ROOT = ROOT / "server" / "app"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" 127.0.0.1 ", "127.0.0.1"),
        ("2001:0db8:0:0:0:0:0:1", "2001:db8::1"),
        ("", UNKNOWN_CLIENT_IP),
        ("not-an-ip", UNKNOWN_CLIENT_IP),
        (None, UNKNOWN_CLIENT_IP),
        ("1" * (MAX_CLIENT_IP_LENGTH + 1), UNKNOWN_CLIENT_IP),
    ],
)
def test_client_ip_normalization_is_canonical_bounded_and_nonempty(
    raw: object | None,
    expected: str,
) -> None:
    normalized = normalize_client_ip(raw)

    assert normalized == expected
    assert normalized
    assert len(normalized) <= MAX_CLIENT_IP_LENGTH


def test_client_ip_is_normalized_once_at_transport_boundaries() -> None:
    paths = (
        APP_ROOT / "transport" / "http" / "public_v1" / "discovery.py",
        APP_ROOT / "transport" / "http" / "public_v1" / "document_uploads.py",
        APP_ROOT / "transport" / "http" / "public_v1" / "research_generation.py",
        APP_ROOT / "transport" / "http" / "public_v1" / "turns.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "http_client_ip(" in source
        assert "def _client_ip" not in source
        assert ".client.host" not in source

    mcp_source = (APP_ROOT / "transport" / "mcp" / "server.py").read_text(
        encoding="utf-8"
    )
    assert "normalize_client_ip(" in mcp_source
    assert 'default="mcp"' not in mcp_source


def test_client_ip_does_not_enter_provenance_or_durable_ledgers() -> None:
    operation_context = (
        APP_ROOT / "shared" / "application" / "operation_context.py"
    ).read_text(encoding="utf-8")
    journal_model = (
        APP_ROOT / "modules" / "operation_journal" / "infrastructure" / "models.py"
    ).read_text(encoding="utf-8")
    invocation_model = (
        APP_ROOT / "database" / "models" / "tool_invocation.py"
    ).read_text(encoding="utf-8")

    assert "client_ip" not in operation_context
    assert "client_ip" not in journal_model
    assert "client_ip" not in invocation_model


@pytest.mark.parametrize(
    ("cloudflare_ip", "expected"),
    [
        ("198.51.100.24", "198.51.100.24"),
        ("2001:db8::24", "2001:db8::24"),
    ],
)
def test_production_cloudflare_chain_uses_the_single_canonical_header(
    cloudflare_ip: str,
    expected: str,
) -> None:
    scope = {
        "type": "http",
        "client": ("10.0.2.18", 443),
        "headers": [
            (b"x-forwarded-for", f"{cloudflare_ip}, 172.64.1.2".encode()),
            (b"cf-connecting-ip", cloudflare_ip.encode()),
        ],
    }

    assert (
        resolve_scope_client_ip(
            scope,  # type: ignore[arg-type]
            environment="production",
            trust_cloudflare=True,
            trusted_proxy_cidr=ip_network("10.0.0.0/16"),
        )
        == expected
    )
    scope["scheme"] = "http"
    scope["headers"].append((b"x-forwarded-proto", b"https"))
    apply_trusted_proxy_scheme(
        scope,  # type: ignore[arg-type]
        environment="production",
        trust_cloudflare=True,
        trusted_proxy_cidr=ip_network("10.0.0.0/16"),
    )
    assert scope["scheme"] == "https"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"cf-connecting-ip", b"not-an-ip")],
        [(b"cf-connecting-ip", b"198.51.100.1, 198.51.100.2")],
        [
            (b"cf-connecting-ip", b"198.51.100.1"),
            (b"cf-connecting-ip", b"198.51.100.2"),
        ],
        [(b"cf-connecting-ip", b" 198.51.100.1")],
        [(b"cf-connecting-ip", b"198.51.100.1\r\nspoofed")],
    ],
)
def test_production_cloudflare_header_fails_closed_when_ambiguous(
    headers: list[tuple[bytes, bytes]],
) -> None:
    scope = {"type": "http", "client": ("10.0.2.18", 443), "headers": headers}

    assert (
        resolve_scope_client_ip(
            scope,  # type: ignore[arg-type]
            environment="production",
            trust_cloudflare=True,
            trusted_proxy_cidr=ip_network("10.0.0.0/16"),
        )
        == UNKNOWN_CLIENT_IP
    )


def test_untrusted_or_nonproduction_requests_ignore_cloudflare_headers() -> None:
    forged = {
        "type": "http",
        "client": ("8.8.8.8", 443),
        "headers": [(b"cf-connecting-ip", b"198.51.100.24")],
    }
    local = {
        "type": "http",
        "client": ("127.0.0.1", 7301),
        "headers": [(b"cf-connecting-ip", b"198.51.100.24")],
    }

    assert (
        resolve_scope_client_ip(
            forged,  # type: ignore[arg-type]
            environment="production",
            trust_cloudflare=True,
            trusted_proxy_cidr=ip_network("10.0.0.0/16"),
        )
        == "8.8.8.8"
    )
    assert (
        resolve_scope_client_ip(
            local,  # type: ignore[arg-type]
            environment="development",
            trust_cloudflare=True,
            trusted_proxy_cidr=None,
        )
        == "127.0.0.1"
    )


@pytest.mark.parametrize(
    "peer",
    ["127.0.0.1", "169.254.10.20", "192.0.2.15", "10.1.0.8"],
)
def test_cloudflare_header_is_rejected_outside_the_exact_vpc_cidr(peer: str) -> None:
    scope = {
        "type": "http",
        "client": (peer, 443),
        "headers": [(b"cf-connecting-ip", b"198.51.100.24")],
    }

    assert resolve_scope_client_ip(
        scope,  # type: ignore[arg-type]
        environment="production",
        trust_cloudflare=True,
        trusted_proxy_cidr=ip_network("10.0.0.0/16"),
    ) == normalize_client_ip(peer)


def test_gunicorn_preserves_raw_alb_peer_for_application_resolution() -> None:
    gunicorn = (ROOT / "server" / "gunicorn.config.py").read_text(encoding="utf-8")
    production = (ROOT / "deploy" / "ecs" / "scholens-production.yml").read_text(
        encoding="utf-8"
    )

    assert 'forwarded_allow_ips = ""' in gunicorn
    assert "proxy_headers = False" in gunicorn
    assert "FORWARDED_ALLOW_IPS" not in production
    assert "TRUST_CLOUDFLARE_CLIENT_IP" in production
    assert "TRUSTED_PROXY_CIDR" in production


@pytest.mark.parametrize(
    ("cloudflare_headers", "expected_ip", "expected_scheme"),
    [
        (
            [
                (b"cf-connecting-ip", b"198.51.100.24"),
                (b"x-forwarded-proto", b"https"),
            ],
            "198.51.100.24",
            "https",
        ),
        ([(b"x-forwarded-proto", b"https")], UNKNOWN_CLIENT_IP, "http"),
        (
            [
                (b"cf-connecting-ip", b"198.51.100.24"),
                (b"cf-connecting-ip", b"198.51.100.25"),
                (b"x-forwarded-proto", b"https"),
            ],
            UNKNOWN_CLIENT_IP,
            "http",
        ),
    ],
)
def test_request_observability_middleware_applies_the_proxy_contract(
    cloudflare_headers: list[tuple[bytes, bytes]],
    expected_ip: str,
    expected_scheme: str,
) -> None:
    observed: dict[str, object] = {}

    async def application(scope, receive, send) -> None:  # noqa: ANN001
        observed["client_ip"] = scope["state"]["client_ip"]
        observed["scheme"] = scope["scheme"]
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    runtime = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(
                trust_cloudflare_client_ip=True,
                trusted_proxy_cidr=ip_network("10.0.0.0/16"),
            )
        )
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/healthz",
        "raw_path": b"/healthz",
        "query_string": b"",
        "root_path": "",
        "headers": cloudflare_headers,
        "client": ("10.0.2.18", 443),
        "server": ("127.0.0.1", 8000),
        "app": runtime,
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        return None

    middleware = RequestObservabilityMiddleware(
        application,
        service="test-api",
        environment="production",
        release="a" * 40,
        success_sample_rate=0,
    )
    asyncio.run(middleware(scope, receive, send))  # type: ignore[arg-type]

    assert observed == {"client_ip": expected_ip, "scheme": expected_scheme}
