from __future__ import annotations

import pytest

from app.bootstrap.runtime_entrypoint import _database_url


def test_database_url_escapes_credentials_and_requires_tls(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_HOST", "db.example.invalid")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_NAME", "sanchezcloud")
    monkeypatch.setenv("DATABASE_USERNAME", "scholens app")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret/value")

    assert _database_url() == (
        "postgresql+psycopg2://scholens%20app:secret%2Fvalue@"
        "db.example.invalid:5432/sanchezcloud"
        "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/global-bundle.pem"
    )


def test_production_database_accepts_only_rds_hostname(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DATABASE_HOST",
        "sanchezcloud-pg.abc.ap-southeast-1.rds.amazonaws.com",
    )
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_NAME", "sanchezcloud")
    monkeypatch.setenv("DATABASE_USERNAME", "scholens_app")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")

    assert "@sanchezcloud-pg.abc.ap-southeast-1.rds.amazonaws.com:5432/" in (
        _database_url()
    )


@pytest.mark.parametrize(
    ("host", "port"),
    [
        ("db.example.com", "5432"),
        ("db.rds.amazonaws.com@attacker.test", "5432"),
        ("db.rds.amazonaws.com/path", "5432"),
        ("db.rds.amazonaws.com?sslmode=disable", "5432"),
        ("db.rds.amazonaws.com#fragment", "5432"),
        ("db.rds.amazonaws.com\r\nX-Injected: value", "5432"),
        ("db.abc.rds.amazonaws.com", "0"),
        ("db.abc.rds.amazonaws.com", "65536"),
        ("db.abc.rds.amazonaws.com", "5432?sslmode=disable"),
    ],
)
def test_production_database_rejects_unsafe_endpoint(
    monkeypatch,
    host: str,
    port: str,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_HOST", host)
    monkeypatch.setenv("DATABASE_PORT", port)
    monkeypatch.setenv("DATABASE_NAME", "sanchezcloud")
    monkeypatch.setenv("DATABASE_USERNAME", "scholens_app")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")

    with pytest.raises(RuntimeError):
        _database_url()
