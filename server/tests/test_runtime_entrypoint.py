from __future__ import annotations

import json
import os
import subprocess

import pytest

from app.bootstrap.runtime_entrypoint import (
    _database_url,
    _identity_database_url,
    _release_sha,
    main,
)


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


def test_identity_database_url_uses_asyncpg_scheme_without_changing_parameters() -> (
    None
):
    application_url = (
        "postgresql+psycopg2://scholens%20app:secret%2Fvalue@"
        "db.example.invalid:5432/sanchezcloud"
        "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/global-bundle.pem"
    )

    assert _identity_database_url(application_url) == application_url.replace(
        "postgresql+psycopg2://", "postgresql://", 1
    )


def test_release_sha_must_be_an_exact_commit(monkeypatch) -> None:
    monkeypatch.delenv("RELEASE_SHA", raising=False)
    with pytest.raises(RuntimeError, match="missing or invalid release SHA"):
        _release_sha()

    monkeypatch.setenv("RELEASE_SHA", "A" * 40)
    with pytest.raises(RuntimeError, match="missing or invalid release SHA"):
        _release_sha()

    monkeypatch.setenv("RELEASE_SHA", "a" * 40)
    assert _release_sha() == "a" * 40


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


def test_migration_fails_when_identity_ledger_is_not_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_HOST", "db.example.invalid")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_NAME", "sanchezcloud")
    monkeypatch.setenv("DATABASE_USERNAME", "scholens_migrator")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")
    monkeypatch.setenv("RELEASE_SHA", "a" * 40)
    monkeypatch.setattr("sys.argv", ["runtime_entrypoint", "migrate"])
    results = iter(
        (
            subprocess.CompletedProcess(
                [],
                0,
                stdout=json.dumps(
                    {
                        "up_to_date": True,
                        "current_revisions": ["head"],
                        "expected_revisions": ["head"],
                    }
                ),
            ),
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, stdout="0\n"),
        )
    )
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return next(results)

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(RuntimeError, match="exactly match"):
        main()

    assert commands == [
        ["scholens", "db", "upgrade", "--yes", "--json"],
        ["sanchezcloud-identity", "check-schema"],
        ["sanchezcloud-identity", "schema-version"],
    ]
    assert "secret" not in repr(commands)
    assert os.environ["AUTH_DATABASE_URL"].startswith("postgresql://")
