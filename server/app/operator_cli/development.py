"""Guarded local-development lifecycle commands."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

import click
from alembic import command
from sqlalchemy import create_engine, text

from app.operator_cli.common import (
    CliState,
    OutputGroup,
    cli_operation,
    confirm,
    current_admin,
    email_callback,
    emit,
    executor,
    guarded,
    load_user,
    mutation_payload,
)

RESET_PHRASE = "RESET-SCHOLENS-LOCAL"
_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")


def _require_reset_url(value: str, *, variable: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2"}
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 55432
        or parsed.path != "/sanchezcloud"
        or not parsed.username
        or bool(parsed.params or parsed.query or parsed.fragment)
    ):
        raise ValueError(f"{variable} must target exactly 127.0.0.1:55432/sanchezcloud")


def _auth_snapshot(database_url: str) -> dict[str, object]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            columns = tuple(
                connection.execute(
                    text(
                        """
                        SELECT table_name, column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'auth'
                        ORDER BY table_name, ordinal_position
                        """
                    )
                ).all()
            )
            user_count = int(
                connection.scalar(text("SELECT COUNT(*) FROM auth.users")) or 0
            )
            version = int(
                connection.scalar(
                    text("SELECT COALESCE(MAX(version), 0) FROM auth.schema_migrations")
                )
                or 0
            )
    finally:
        engine.dispose()
    return {"columns": columns, "user_count": user_count, "version": version}


def _apply_local_grants(admin_url: str) -> None:
    parsed = urlparse(admin_url)
    roles = {
        "auth_migrator_role": os.getenv("AUTH_MIGRATION_ROLE", "auth_migrator"),
        "product_migrator_role": os.getenv(
            "SCHOLENS_MIGRATION_ROLE", "scholens_migrator"
        ),
        "app_role": os.getenv("SCHOLENS_APP_ROLE", "scholens_app"),
    }
    if any(not _ROLE_PATTERN.fullmatch(role) for role in roles.values()):
        raise ValueError("Database role names must be lowercase SQL identifiers")
    bootstrap = (
        Path(__file__).resolve().parents[3] / "deploy/production/bootstrap-db.sql"
    )
    environment = os.environ.copy()
    if parsed.password:
        environment["PGPASSWORD"] = unquote(parsed.password)
    args = [
        "psql",
        "--host",
        parsed.hostname or "127.0.0.1",
        "--port",
        str(parsed.port or 55432),
        "--username",
        unquote(parsed.username or ""),
        "--dbname",
        parsed.path.lstrip("/"),
    ]
    for name, role in roles.items():
        args.extend(["-v", f"{name}={role}"])
    args.extend(["-f", str(bootstrap)])
    subprocess.run(args, check=True, env=environment)


@click.group("dev", cls=OutputGroup)
def development_group() -> None:
    """Prepare verified accounts and reset only local product data."""


@development_group.command("bootstrap-account")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option("--email", required=True, callback=email_callback)
@click.option("--reason", required=True)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def bootstrap_account(
    state: CliState,
    actor_email: str,
    email: str,
    reason: str,
    yes: bool,
) -> None:
    from app.modules.identity.application.identity import AuthenticatedIdentity

    del reason
    actor_user = load_user(actor_email)
    target = load_user(email)
    confirm(f"Create the Scholens profile for existing identity {email}?", yes=yes)
    _, changed = executor().command(
        lambda capabilities: capabilities.identity.bootstrap_profile(
            actor=current_admin(capabilities, actor_user.id),
            operation=cli_operation("dev.bootstrap-account"),
            identity=AuthenticatedIdentity(
                id=target.id,
                email=target.email,
                display_name=target.display_name,
                status=str(target.status),
                email_verified=target.email_verified_at is not None,
            ),
        )
    )
    emit(
        state,
        mutation_payload(changed=changed, email=email),
        human=f"{email}: {'changed' if changed else 'unchanged'}",
    )


@development_group.command("reset-product")
@click.option(
    "--confirm",
    "confirmation",
    prompt=f"Type {RESET_PHRASE}",
    help="Required exact destructive confirmation phrase.",
)
@click.pass_obj
@guarded
def reset_product(state: CliState, confirmation: str) -> None:
    from app.operator_cli.database import alembic_config

    if confirmation != RESET_PHRASE:
        raise click.ClickException("The reset confirmation phrase did not match.")
    admin_url = os.getenv("LOCAL_DATABASE_ADMIN_URL", "")
    migration_url = os.getenv("SCHOLENS_MIGRATION_DATABASE_URL", "")
    _require_reset_url(admin_url, variable="LOCAL_DATABASE_ADMIN_URL")
    _require_reset_url(
        migration_url,
        variable="SCHOLENS_MIGRATION_DATABASE_URL",
    )
    migration_role = os.getenv("SCHOLENS_MIGRATION_ROLE", "scholens_migrator")
    if not _ROLE_PATTERN.fullmatch(migration_role):
        raise ValueError("SCHOLENS_MIGRATION_ROLE is not a safe SQL identifier")
    if urlparse(migration_url).username != migration_role:
        raise ValueError(
            "SCHOLENS_MIGRATION_DATABASE_URL must authenticate as "
            "SCHOLENS_MIGRATION_ROLE"
        )

    auth_before = _auth_snapshot(admin_url)
    engine = create_engine(admin_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS scholens CASCADE"))
            connection.execute(
                text(f'CREATE SCHEMA scholens AUTHORIZATION "{migration_role}"')
            )
    finally:
        engine.dispose()
    command.upgrade(alembic_config(database_url=migration_url), "head")
    _apply_local_grants(admin_url)
    auth_after = _auth_snapshot(admin_url)
    if auth_after != auth_before:
        raise RuntimeError("auth schema verification changed during product reset")
    emit(
        state,
        {
            "status": "changed",
            "schema": "scholens",
            "auth_unchanged": True,
        },
        human="Reset and migrated only the local scholens schema; auth is unchanged.",
    )


__all__ = ["RESET_PHRASE", "development_group"]
