import pytest
from app.bootstrap.settings import AppSettings
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _clear_cache_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep dotenv-loaded cache settings from overriding constructor inputs."""
    for name in (
        "CACHE_URL",
        "CACHE_HOST",
        "CACHE_PORT",
        "CACHE_USERNAME",
        "CACHE_PASSWORD",
        "CACHE_TLS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_production_requires_a_dedicated_search_cursor_secret() -> None:
    with pytest.raises(ValidationError):
        AppSettings(
            _env_file=None,
            environment="production",
            paper_search_cursor_secret="development-only-search-cursor-secret",
        )


def test_production_accepts_a_dedicated_search_cursor_secret() -> None:
    settings = AppSettings(
        _env_file=None,
        environment="production",
        paper_search_cursor_secret="production-search-cursor-secret-value",
        project_invitation_token_secret="production-invitation-secret-value",
        integration_credential_encryption_key=(
            "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M="
        ),
        scholight_mcp_delegation_jwt_secret="s" * 32,
        cache_url=(
            "rediss://api:secret@scholens.abc.0001.apse1.cache.amazonaws.com:6379/0"
        ),
    )

    assert settings.environment == "production"


def test_production_cache_endpoint_is_composed_without_exposing_credentials() -> None:
    settings = AppSettings(
        _env_file=None,
        cache_host="cache.example.invalid",
        cache_username="api user",
        cache_password="secret/value",
        cache_tls=True,
    )

    assert settings.resolved_cache_url == (
        "rediss://api%20user:secret%2Fvalue@cache.example.invalid:6379/0"
    )


def test_production_cache_rejects_missing_credentials_and_unmanaged_host() -> None:
    common = {
        "environment": "production",
        "paper_search_cursor_secret": "production-search-cursor-secret-value",
        "project_invitation_token_secret": "production-invitation-secret-value",
        "integration_credential_encryption_key": (
            "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M="
        ),
        "scholight_mcp_delegation_jwt_secret": "s" * 32,
        "cache_tls": True,
    }
    with pytest.raises(ValidationError, match="CACHE_USERNAME is required"):
        AppSettings(
            _env_file=None,
            **common,
            cache_host="scholens.abc.0001.apse1.cache.amazonaws.com",
        )
    with pytest.raises(ValidationError, match="managed-service hostname"):
        AppSettings(
            _env_file=None,
            **common,
            cache_host="cache.example.invalid",
            cache_username="api",
            cache_password="secret",
        )


def test_cors_allowed_origins_supports_parallel_frontends() -> None:
    settings = AppSettings(
        _env_file=None,
        client_domain="http://localhost:3000",
        client_allowed_origins=(
            "http://localhost:3000, http://localhost:3001,http://localhost:3000"
        ),
    )

    assert settings.cors_allowed_origins == [
        "http://localhost:3000",
        "http://localhost:3001",
    ]


def test_cors_allowed_origins_defaults_to_canonical_client_domain() -> None:
    settings = AppSettings(
        _env_file=None,
        client_domain="http://localhost:3000",
        client_allowed_origins=None,
    )

    assert settings.cors_allowed_origins == ["http://localhost:3000"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_invitation_delivery_interval_seconds", 0),
        ("project_invitation_delivery_lease_seconds", 39),
    ],
)
def test_invitation_delivery_settings_reject_unsafe_timing(
    field: str,
    value: float,
) -> None:
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **{field: value})


@pytest.mark.parametrize("trusted_proxy_cidr", [None, "not-a-cidr"])
def test_production_cloudflare_trust_requires_a_valid_proxy_cidr(
    trusted_proxy_cidr: str | None,
) -> None:
    with pytest.raises(ValidationError, match="TRUSTED_PROXY_CIDR|validation error"):
        AppSettings(
            _env_file=None,
            environment="production",
            paper_search_cursor_secret="production-search-cursor-secret-value",
            integration_credential_encryption_key=(
                "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M="
            ),
            scholight_mcp_delegation_jwt_secret="s" * 32,
            cache_url=(
                "rediss://api:secret@scholens.abc.0001.apse1.cache.amazonaws.com:6379/0"
            ),
            trust_cloudflare_client_ip=True,
            trusted_proxy_cidr=trusted_proxy_cidr,
        )
