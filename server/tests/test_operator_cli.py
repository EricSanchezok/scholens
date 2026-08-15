from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner
from sqlalchemy.exc import OperationalError

from app.cli import cli
from app.operator_cli import database
from app.operator_cli import health
from app.operator_cli import usage, users


class _ScalarPage:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def unique(self) -> _ScalarPage:
        return self

    def __iter__(self):
        return iter(self._values)


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
        "_job_broker",
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
        "_job_broker",
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


def test_production_doctor_checks_predefined_sqs_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_urls = {
        "SQS_DOCUMENT_QUEUE_URL": "https://sqs.ap-southeast-1.amazonaws.com/123/document",
        "SQS_RESEARCH_QUEUE_URL": "https://sqs.ap-southeast-1.amazonaws.com/123/research",
        "SQS_MAINTENANCE_QUEUE_URL": "https://sqs.ap-southeast-1.amazonaws.com/123/maintenance",
    }
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CELERY_BROKER_URL", "sqs://")
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    for name, value in queue_urls.items():
        monkeypatch.setenv(name, value)

    client = MagicMock()
    monkeypatch.setattr(health.boto3, "client", lambda *args, **kwargs: client)

    result = health._job_broker()

    assert result == {
        "reachable": True,
        "transport": "sqs",
        "queues": ["document", "maintenance", "research"],
    }
    assert client.get_queue_attributes.call_count == 3
    assert {
        call.kwargs["QueueUrl"] for call in client.get_queue_attributes.call_args_list
    } == set(queue_urls.values())
    assert all(
        call.kwargs["AttributeNames"] == ["QueueArn"]
        for call in client.get_queue_attributes.call_args_list
    )
    assert health._jobs() == {
        "reachable": True,
        "deployed": False,
        "mode": "worker-only",
    }


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
        lambda: {
            "up_to_date": True,
            "current_revisions": ["head"],
            "expected_revisions": ["head"],
            "schema_owned_by_role": True,
        },
    )
    upgrade = MagicMock()
    monkeypatch.setattr(database.command, "upgrade", upgrade)

    result = CliRunner().invoke(cli, ["db", "upgrade", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "unchanged"
    upgrade.assert_not_called()


def test_database_upgrade_fails_when_ledger_does_not_reach_unique_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database, "migration_database_url", lambda: "postgresql://x")
    statuses = iter(
        (
            {
                "up_to_date": False,
                "current_revisions": ["old"],
                "expected_revisions": ["head"],
                "schema_owned_by_role": True,
            },
            {
                "up_to_date": False,
                "current_revisions": ["old"],
                "expected_revisions": ["head"],
                "schema_owned_by_role": True,
            },
        )
    )
    monkeypatch.setattr(database, "migration_status", lambda: next(statuses))
    monkeypatch.setattr(database.command, "upgrade", MagicMock())

    result = CliRunner().invoke(cli, ["db", "upgrade", "--yes", "--json"])

    assert result.exit_code == 1
    assert "did not converge to the one expected Scholens head" in result.output


def test_database_upgrade_rejects_non_owner_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database, "migration_database_url", lambda: "postgresql://x")
    monkeypatch.setattr(
        database,
        "migration_status",
        lambda: {"up_to_date": False, "schema_owned_by_role": False},
    )
    upgrade = MagicMock()
    monkeypatch.setattr(database.command, "upgrade", upgrade)

    result = CliRunner().invoke(cli, ["db", "upgrade", "--json"])

    assert result.exit_code == 1
    assert "must own the scholens schema" in result.output
    upgrade.assert_not_called()


def test_alembic_config_uses_explicit_deployed_server_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deployed_root = tmp_path / "app"
    migrations = deployed_root / "migrations"
    migrations.mkdir(parents=True)
    (deployed_root / "alembic.ini").write_text(
        "[alembic]\nscript_location = migrations\n",
        encoding="utf-8",
    )
    (migrations / "env.py").write_text("", encoding="utf-8")
    fake_installed_module = (
        tmp_path
        / ".venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "app"
        / "operator_cli"
        / "database.py"
    )
    monkeypatch.setattr(database, "__file__", str(fake_installed_module))
    monkeypatch.setenv("SCHOLENS_SERVER_ROOT", str(deployed_root))

    config = database.alembic_config(database_url="postgresql://fixture")

    assert config.config_file_name == str(deployed_root / "alembic.ini")
    assert config.get_main_option("script_location") == str(migrations)


def test_alembic_config_fails_cleanly_when_deployed_bundle_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SCHOLENS_SERVER_ROOT", str(tmp_path / "missing"))

    with pytest.raises(ValueError, match="SCHOLENS_SERVER_ROOT"):
        database.alembic_config()


def test_database_dependency_error_is_stable_redacted_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        database,
        "migration_status",
        lambda: (_ for _ in ()).throw(
            OperationalError(
                "postgresql://operator:super-secret@database.example/sanchezcloud",
                {},
                OSError("database unavailable"),
            )
        ),
    )

    result = CliRunner().invoke(cli, ["db", "status", "--json"])
    payload = json.loads(result.output)

    assert result.exit_code == 1
    assert payload["error"]["code"] == "command_failed"
    assert "super-secret" not in result.output
    assert "operator:***@database.example" in result.output


def test_identity_commands_do_not_collect_an_unpersisted_reason() -> None:
    runner = CliRunner()
    for command in ("grant-admin", "revoke-admin", "block", "unblock"):
        result = runner.invoke(cli, ["users", command, "--help"])

        assert result.exit_code == 0
        assert "--reason" not in result.output

        rejected = runner.invoke(
            cli,
            [
                "users",
                command,
                "--actor-email",
                "admin@example.com",
                "--email",
                "target@example.com",
                "--reason",
                "discarded prose",
                "--yes",
            ],
        )
        assert rejected.exit_code == 2
        assert "No such option" in rejected.output
        assert "--reason" in rejected.output


@pytest.mark.parametrize(
    ("command", "required_options"),
    [
        (
            ("dev", "bootstrap-account"),
            ("--actor-email", "admin@example.com", "--email", "target@example.com"),
        ),
        (
            ("maintenance", "backfill-passages"),
            ("--actor-email", "admin@example.com"),
        ),
    ],
)
def test_non_prose_commands_reject_an_unpersisted_reason(
    command: tuple[str, str],
    required_options: tuple[str, ...],
) -> None:
    runner = CliRunner()
    help_result = runner.invoke(cli, [*command, "--help"])

    assert help_result.exit_code == 0
    assert "--reason" not in help_result.output

    rejected = runner.invoke(
        cli,
        [*command, *required_options, "--reason", "discarded prose", "--yes"],
    )
    assert rejected.exit_code == 2
    assert "No such option" in rejected.output
    assert "--reason" in rejected.output


def test_users_plan_filter_scans_beyond_first_five_hundred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    first_page = [MagicMock(id=index) for index in range(1, 501)]
    late_match = MagicMock(id=501)
    db.scalars.side_effect = [
        _ScalarPage(first_page),
        _ScalarPage([late_match]),
    ]
    monkeypatch.setattr(
        users,
        "_entitlement_resolution",
        lambda _db, user: MagicMock(
            plan=MagicMock(value="researcher" if user.id == 501 else "basic")
        ),
    )
    summary = MagicMock(side_effect=lambda _db, user, **_kwargs: {"id": user.id})
    monkeypatch.setattr(users, "_summary", summary)

    from app.database.models import AuthUser
    from sqlalchemy import select

    rows = users._list_summaries(
        db,
        select(AuthUser),
        plan="researcher",
        limit=1,
    )

    assert rows == [{"id": 501}]
    assert db.scalars.call_count == 2
    summary.assert_called_once()


def test_usage_plan_filter_scans_beyond_first_five_hundred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def token_row(user_id: int) -> tuple[object, ...]:
        return (
            user_id,
            f"user-{user_id}@example.com",
            "chat",
            "standard",
            "deepseek",
            "fixture",
            1,
            1,
            0,
            0,
            0,
            2,
            0,
        )

    db = MagicMock()
    first_page = [token_row(index) for index in range(1, 501)]
    second_page = [token_row(501)]
    first_result = MagicMock()
    first_result.all.return_value = first_page
    second_result = MagicMock()
    second_result.all.return_value = second_page
    db.execute.side_effect = [first_result, second_result]
    first_users = [MagicMock(id=index) for index in range(1, 501)]
    late_user = MagicMock(id=501)
    db.scalars.side_effect = [
        _ScalarPage(first_users),
        _ScalarPage([late_user]),
    ]
    session_context = MagicMock()
    session_context.__enter__.return_value = db
    monkeypatch.setattr(usage, "SessionLocal", session_context, raising=False)

    import app.database.database as database_module
    import app.modules.billing.infrastructure.quotas as quotas_module
    import app.modules.identity.infrastructure.users as identity_users

    monkeypatch.setattr(database_module, "SessionLocal", lambda: session_context)
    monkeypatch.setattr(identity_users, "actor_from_auth_user", lambda user: user)
    monkeypatch.setattr(
        quotas_module,
        "get_user_entitlements",
        lambda _db, user: MagicMock(
            plan=MagicMock(value="researcher" if user.id == 501 else "basic"),
            source="grant" if user.id == 501 else "basic",
        ),
    )

    rows = usage._token_rows(
        email=None,
        plan="researcher",
        feature=None,
        profile=None,
        model=None,
        week_start=None,
        limit=1,
    )

    assert [row["user_id"] for row in rows] == [501]
    assert db.execute.call_count == 2


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
