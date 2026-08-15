from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.operator_cli import database
from app.operator_cli import health


@pytest.mark.parametrize(
    "command",
    [
        "contract",
        "db",
        "dev",
        "entitlements",
        "jobs",
        "maintenance",
        "usage",
        "users",
        "verify",
    ],
)
def test_every_cli_group_has_stable_help(command: str) -> None:
    result = CliRunner().invoke(cli, [command, "--help"])

    assert result.exit_code == 0
    assert "--json" in result.output


def test_invalid_email_is_a_click_parameter_error() -> None:
    result = CliRunner().invoke(cli, ["users", "show", "--email", "not-an-email"])

    assert result.exit_code == 2
    assert "must be a complete email address" in result.output


def test_doctor_json_is_machine_readable_and_never_calls_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "_configuration",
        "_database",
        "_migration",
        "_redis",
        "_rabbitmq",
        "_jobs",
        "_s3",
        "_ai_profiles",
    ):
        monkeypatch.setattr(health, name, lambda: {"reachable": True})

    result = CliRunner().invoke(cli, ["doctor", "--json"])
    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert payload["ok"] is True
    assert len(payload["checks"]) == 8


def test_doctor_failure_is_json_exit_one_and_redacts_url_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "_configuration",
        "_migration",
        "_redis",
        "_rabbitmq",
        "_jobs",
        "_s3",
        "_ai_profiles",
    ):
        monkeypatch.setattr(health, name, lambda: {"reachable": True})

    def fail_database() -> dict[str, object]:
        raise RuntimeError(
            "postgresql://operator:super-secret@database.example/sanchezcloud"
        )

    monkeypatch.setattr(health, "_database", fail_database)
    result = CliRunner().invoke(cli, ["doctor", "--json"])
    payload = json.loads(result.output)

    assert result.exit_code == 1
    assert payload["ok"] is False
    assert "super-secret" not in result.output
    assert "operator:***@database.example" in result.output


def test_reset_requires_the_exact_confirmation_phrase() -> None:
    result = CliRunner().invoke(cli, ["dev", "reset-product"], input="WRONG\n")

    assert result.exit_code == 1
    assert "confirmation phrase did not match" in result.output


def test_database_upgrade_reports_unchanged_without_running_alembic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database, "migration_database_url", lambda: "postgresql://x")
    monkeypatch.setattr(
        database,
        "migration_status",
        lambda: {"up_to_date": True, "current_revisions": ["head"]},
    )
    upgrade = MagicMock()
    monkeypatch.setattr(database.command, "upgrade", upgrade)

    result = CliRunner().invoke(cli, ["db", "upgrade", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "unchanged"
    upgrade.assert_not_called()


def test_contract_export_reports_unchanged_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.transport.http.contract_artifacts.check_contract",
        lambda: (),
    )

    def unexpected_export() -> object:
        raise AssertionError("current artifacts must not be rewritten")

    monkeypatch.setattr(
        "app.transport.http.contract_artifacts.export_contract",
        unexpected_export,
    )
    result = CliRunner().invoke(cli, ["contract", "export", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"files": [], "status": "unchanged"}


def test_every_sqladmin_business_view_is_read_only() -> None:
    from app.database import admin

    views = [
        value
        for name, value in vars(admin).items()
        if name.endswith("Admin")
        and isinstance(value, type)
        and issubclass(value, admin.ReadOnlyModelView)
    ]

    assert views
    assert all(view.can_create is False for view in views)
    assert all(view.can_edit is False for view in views)
    assert all(view.can_delete is False for view in views)
