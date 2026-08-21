from __future__ import annotations

import json
import os
import subprocess
from unittest.mock import MagicMock

import pytest

from app.bootstrap.runtime_entrypoint import (
    _assert_shared_avatar_runtime_privileges,
    _database_url,
    _identity_database_url,
    _release_sha,
    main,
)
from sanchezcloud_identity import AUTH_SCHEMA_VERSION


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


@pytest.mark.parametrize(
    "privileges",
    [
        (False, False, False, False),
        (True, True, False, False),
        (True, False, True, False),
        (True, False, False, True),
    ],
)
def test_shared_avatar_runtime_privilege_audit_rejects_drift(
    monkeypatch: pytest.MonkeyPatch,
    privileges: tuple[bool, bool, bool, bool],
) -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.one.return_value = privileges
    monkeypatch.setattr(
        "app.bootstrap.runtime_entrypoint.create_engine",
        lambda _database_url: engine,
    )

    with pytest.raises(RuntimeError, match="SELECT-only"):
        _assert_shared_avatar_runtime_privileges("postgresql://fixture")

    engine.dispose.assert_called_once_with()


def test_shared_avatar_runtime_privilege_audit_accepts_read_only_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.one.return_value = (True, False, False, False)
    monkeypatch.setattr(
        "app.bootstrap.runtime_entrypoint.create_engine",
        lambda _database_url: engine,
    )

    _assert_shared_avatar_runtime_privileges("postgresql://fixture")

    statement = str(connection.execute.call_args.args[0])
    assert "auth.user_avatars" in statement
    assert "scholens_app" in statement
    engine.dispose.assert_called_once_with()


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


def test_runtime_entrypoint_executes_dedicated_conversation_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_HOST", "db.example.invalid")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_NAME", "sanchezcloud")
    monkeypatch.setenv("DATABASE_USERNAME", "scholens_app")
    monkeypatch.setenv("DATABASE_PASSWORD", "secret")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr("sys.argv", ["runtime_entrypoint", "conversation-worker"])
    executed: list[list[str]] = []

    def execute(_program: str, command: list[str]) -> None:
        executed.append(command)

    monkeypatch.setattr(os, "execvp", execute)

    assert main() == 0
    assert executed[0][:4] == [
        "celery",
        "--app",
        "app.modules.conversations.infrastructure.celery_app",
        "worker",
    ]
    assert "--queues=conversation" in executed[0]


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


def test_migration_emits_no_proof_when_avatar_runtime_privileges_drift(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
            subprocess.CompletedProcess([], 0, stdout=f"{AUTH_SCHEMA_VERSION}\n"),
        )
    )
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: next(results))

    def reject_privilege_drift(_database_url: str) -> None:
        raise RuntimeError("shared avatar runtime privileges must be SELECT-only")

    monkeypatch.setattr(
        "app.bootstrap.runtime_entrypoint._assert_shared_avatar_runtime_privileges",
        reject_privilege_drift,
    )

    with pytest.raises(RuntimeError, match="SELECT-only"):
        main()

    assert "SCHOLENS_MIGRATION_PROOF=" not in capsys.readouterr().out
