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


def migration_database_url() -> str:
    value = os.getenv("SCHOLENS_MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not value:
        raise ValueError(
            "SCHOLENS_MIGRATION_DATABASE_URL is required for database operations"
        )
    return value


def alembic_config(*, database_url: str | None = None) -> Config:
    root = Path(__file__).resolve().parents[2]
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
    if before["up_to_date"]:
        emit(
            state,
            {"status": "unchanged", **before},
            human="Scholens schema is already current.",
        )
        return
    confirm("Apply all pending Scholens product migrations?", yes=yes)
    command.upgrade(alembic_config(database_url=database_url), "head")
    payload = migration_status()
    emit(state, {"status": "changed", **payload}, human="Scholens schema is current.")


__all__ = ["database_group", "migration_status"]
