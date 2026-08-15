"""Migration inspection and execution commands."""

from __future__ import annotations

import os
from pathlib import Path

import click
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.operator_cli.common import CliState, OutputGroup, confirm, emit, guarded

SERVER_ROOT_ENV = "SCHOLENS_SERVER_ROOT"


def migration_database_url() -> str:
    value = os.getenv("SCHOLENS_MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not value:
        raise ValueError(
            "SCHOLENS_MIGRATION_DATABASE_URL is required for database operations"
        )
    return value


def server_root() -> Path:
    """Locate the deployed migration bundle, not the installed Python package."""
    configured = os.getenv(SERVER_ROOT_ENV)
    candidates = (
        (Path(configured).expanduser(),)
        if configured
        else (Path(__file__).resolve().parents[2], Path.cwd())
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "alembic.ini").is_file() and (
            resolved / "migrations" / "env.py"
        ).is_file():
            return resolved
    raise ValueError(
        f"{SERVER_ROOT_ENV} must identify a directory containing "
        "alembic.ini and migrations/env.py"
    )


def alembic_config(*, database_url: str | None = None) -> Config:
    root = server_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def migration_status() -> dict[str, object]:
    database_url = migration_database_url()
    config = alembic_config(database_url=database_url)
    expected = tuple(ScriptDirectory.from_config(config).get_heads())
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            current_user = str(connection.scalar(text("SELECT current_user")))
            owns_schema = connection.scalar(
                text(
                    "SELECT pg_get_userbyid(nspowner) = current_user "
                    "FROM pg_namespace WHERE nspname = 'scholens'"
                )
            )
            context = MigrationContext.configure(
                connection,
                opts={
                    "version_table": "schema_migrations",
                    "version_table_schema": "scholens",
                },
            )
            current = tuple(context.get_current_heads())
    finally:
        engine.dispose()
    return {
        "database_reachable": True,
        "database_role": current_user,
        "schema_owned_by_role": owns_schema is True,
        "current_revisions": current,
        "expected_revisions": expected,
        "up_to_date": set(current) == set(expected),
    }


def _require_unique_current_head(payload: dict[str, object]) -> None:
    expected_value = payload.get("expected_revisions")
    current_value = payload.get("current_revisions")
    if not isinstance(expected_value, (list, tuple)) or not all(
        isinstance(value, str) for value in expected_value
    ):
        raise RuntimeError("expected migration revisions are malformed")
    if not isinstance(current_value, (list, tuple)) or not all(
        isinstance(value, str) for value in current_value
    ):
        raise RuntimeError("current migration revisions are malformed")
    expected = tuple(expected_value)
    current = tuple(current_value)
    if (
        len(expected) != 1
        or current != expected
        or payload.get("up_to_date") is not True
    ):
        raise RuntimeError(
            "migration did not converge to the one expected Scholens head"
        )


@click.group("db", cls=OutputGroup)
def database_group() -> None:
    """Inspect or explicitly migrate the Scholens schema."""


@database_group.command("status")
@click.pass_obj
@guarded
def status_command(state: CliState) -> None:
    payload = migration_status()
    emit(state, payload)
    if not payload["up_to_date"]:
        raise click.exceptions.Exit(1)


@database_group.command("upgrade")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def upgrade_command(state: CliState, yes: bool) -> None:
    database_url = migration_database_url()
    before = migration_status()
    if before.get("schema_owned_by_role") is not True:
        raise click.ClickException(
            "The migration database role must own the scholens schema."
        )
    if before["up_to_date"]:
        _require_unique_current_head(before)
        emit(
            state,
            {"status": "unchanged", **before},
            human="Scholens schema is already current.",
        )
        return
    confirm("Apply all pending Scholens product migrations?", yes=yes)
    command.upgrade(alembic_config(database_url=database_url), "head")
    payload = migration_status()
    _require_unique_current_head(payload)
    emit(state, {"status": "changed", **payload}, human="Scholens schema is current.")


__all__ = ["database_group", "migration_status"]
