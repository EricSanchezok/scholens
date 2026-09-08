"""Production single-host composition uses the same strict runtime contract."""

from app.bootstrap.cache_endpoint import cache_url_from_environment
from app.bootstrap.runtime_entrypoint import _database_url
from app.bootstrap.settings import AppSettings


def test_single_host_database_keeps_verify_full_and_explicit_ca(monkeypatch) -> None:
    for key, value in {
        "ENVIRONMENT": "production",
        "RUNTIME_DEPLOYMENT_MODE": "single-host",
        "DATABASE_HOST": "postgres.personal.svc.sanchezcloud",
        "DATABASE_PORT": "5432",
        "DATABASE_NAME": "sanchezcloud",
        "DATABASE_USERNAME": "scholens_app",
        "DATABASE_PASSWORD": "fixture/value",
        "AUTH_PG_SSL_ROOT_CERT": "/run/trust/private-ca.pem",
    }.items():
        monkeypatch.setenv(key, value)
    assert _database_url() == (
        "postgresql+psycopg2://scholens_app:fixture%2Fvalue@"
        "postgres.personal.svc.sanchezcloud:5432/sanchezcloud"
        "?sslmode=verify-full&sslrootcert=/run/trust/private-ca.pem"
    )


def test_single_host_cache_mode_reaches_environment_adapter(monkeypatch) -> None:
    monkeypatch.delenv("CACHE_URL", raising=False)
    for key, value in {
        "ENVIRONMENT": "production",
        "RUNTIME_DEPLOYMENT_MODE": "single-host",
        "CACHE_HOST": "cache.personal.svc.sanchezcloud",
        "CACHE_PORT": "6380",
        "CACHE_USERNAME": "api",
        "CACHE_PASSWORD": "fixture",
        "CACHE_TLS": "true",
    }.items():
        monkeypatch.setenv(key, value)
    assert cache_url_from_environment() == (
        "rediss://api:fixture@cache.personal.svc.sanchezcloud:6380/0"
    )


def test_single_host_cache_mode_reaches_settings_adapter() -> None:
    settings = AppSettings(
        _env_file=None,
        environment="production",
        runtime_deployment_mode="single-host",
        cache_url="rediss://api:fixture@cache.personal.svc.sanchezcloud:6380/0",
        paper_search_cursor_secret="production-search-cursor-secret-value",
        project_invitation_token_secret="production-invitation-secret-value",
        integration_credential_encryption_key=(
            "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M="
        ),
        scholight_mcp_delegation_jwt_secret="s" * 32,
    )
    assert settings.resolved_cache_url == settings.cache_url
