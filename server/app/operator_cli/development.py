"""Guarded local-development lifecycle commands."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
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
_SYNTHETIC_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
}


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


def _require_local_test_account_target(database_url: str, *, email: str) -> None:
    if os.getenv("ENVIRONMENT", "development").casefold() != "development":
        raise ValueError("Test-account seeding is available only in development")
    parsed = urlparse(database_url)
    if (
        parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2"}
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 55432
        or parsed.path != "/sanchezcloud"
        or parsed.username != "scholens_app"
        or bool(parsed.params or parsed.query or parsed.fragment)
    ):
        raise ValueError(
            "Test-account seeding requires scholens_app at exactly "
            "127.0.0.1:55432/sanchezcloud"
        )
    domain = email.rpartition("@")[2].casefold()
    if domain not in _SYNTHETIC_EMAIL_DOMAINS:
        raise ValueError("Test-account email must use a reserved synthetic domain")


def _password_callback(
    _context: click.Context,
    _parameter: click.Parameter,
    value: str | None,
) -> str | None:
    if value is not None and len(value) < 12:
        raise click.BadParameter("must contain at least 12 characters")
    return value


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
        Path(__file__).resolve().parents[3] / "deploy/ecs/database-bootstrap.sql"
    )
    environment = os.environ.copy()
    if parsed.password:
        environment["PGPASSWORD"] = unquote(parsed.password)
    psql = shutil.which("psql")
    if psql is None:
        for candidate in (
            "/opt/homebrew/opt/libpq/bin/psql",
            "/usr/local/opt/libpq/bin/psql",
        ):
            if Path(candidate).is_file():
                psql = candidate
                break
    if psql is None:
        raise FileNotFoundError(
            "psql is required to reapply local grants; install PostgreSQL client tools"
        )
    args = [
        psql,
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


@development_group.command("seed-test-account")
@click.option(
    "--email",
    default="developer@example.com",
    show_default=True,
    callback=email_callback,
)
@click.option("--display-name", default="Local Developer", show_default=True)
@click.option(
    "--password",
    envvar="SCHOLENS_DEV_TEST_PASSWORD",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    callback=_password_callback,
    help=(
        "Synthetic-account password. Prefer SCHOLENS_DEV_TEST_PASSWORD or the "
        "hidden prompt instead of a command-line value."
    ),
)
@click.option(
    "--bootstrap-admin",
    is_flag=True,
    help="Grant administrator access only when no Scholens administrator exists.",
)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def seed_test_account(
    state: CliState,
    email: str,
    display_name: str,
    password: str,
    bootstrap_admin: bool,
    yes: bool,
) -> None:
    """Create or repair one verified synthetic account in shared-local Identity."""
    from app.modules.identity.application.identity import AuthenticatedIdentity
    from app.operator_cli.local_test_account import seed_local_test_identity
    from app.shared.domain import AppError

    database_url = os.getenv("AUTH_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
    _require_local_test_account_target(database_url, email=email)
    confirm(
        f"Seed verified local test account {email}? Existing sessions may be revoked.",
        yes=yes,
    )
    result = asyncio.run(
        seed_local_test_identity(
            database_url=database_url,
            email=email,
            password=password,
            display_name=display_name,
            jwt_secret=os.getenv(
                "AUTH_JWT_SECRET",
                "development-only-scholens-auth-secret",
            ),
        )
    )
    actor = executor().command(
        lambda capabilities: capabilities.identity.resolve_actor(
            AuthenticatedIdentity(
                id=result.user_id,
                email=result.email,
                display_name=display_name,
                status="active",
                email_verified=True,
            ),
            operation=cli_operation("dev.seed-test-account", system=True),
        )
    )
    admin_bootstrapped = False
    if bootstrap_admin and not actor.is_admin:
        try:
            admin_result = executor().command(
                lambda capabilities: capabilities.identity.bootstrap_admin(
                    operation=cli_operation(
                        "dev.seed-test-account.bootstrap-admin",
                        system=True,
                    ),
                    user_id=result.user_id,
                )
            )
            admin_bootstrapped = admin_result.changed
        except AppError as exc:
            if exc.code != "admin_bootstrap_closed":
                raise
            raise ValueError(
                "Another Scholens administrator already exists; use users grant-admin "
                "with an explicit administrator actor"
            ) from exc
    changed = result.changed or admin_bootstrapped
    payload = {
        "changed": changed,
        "created": result.created,
        "email": result.email,
        "email_verified": result.verified,
        "password_changed": result.password_changed,
        "profile_changed": result.profile_changed,
        "is_admin": actor.is_admin or admin_bootstrapped,
    }
    emit(
        state,
        payload,
        human=(
            f"{result.email}: {'changed' if changed else 'unchanged'}; "
            f"verified; admin={'yes' if payload['is_admin'] else 'no'}"
        ),
    )


@development_group.command("bootstrap-account")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option("--email", required=True, callback=email_callback)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def bootstrap_account(
    state: CliState,
    actor_email: str,
    email: str,
    yes: bool,
) -> None:
    from app.modules.identity.application.identity import AuthenticatedIdentity

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


@development_group.command("seed-test-fixture")
@click.option(
    "--email",
    default="developer@example.com",
    show_default=True,
    callback=email_callback,
)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def seed_test_fixture(state: CliState, email: str, yes: bool) -> None:
    """Seed deterministic local PDFs and a Project for one test account."""
    database_url = os.getenv("DATABASE_URL", "")
    _require_local_test_account_target(database_url, email=email)
    confirm(
        f"Seed local PDF and Project fixture for {email}? Existing matching fixture "
        "rows will be reused.",
        yes=yes,
    )
    from app.operator_cli.local_fixture import seed_local_fixture

    result = seed_local_fixture(email=email)
    emit(
        state,
        {
            "changed": any(
                result[key]
                for key in (
                    "created_documents",
                    "created_library_entries",
                    "created_project_links",
                )
            ),
            **result,
        },
        human=(
            f"{email}: {result['documents']} PDFs in "
            f"Project {result['project_title']} ({result['project_id']})"
        ),
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
