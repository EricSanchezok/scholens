"""Unified Scholens operator command line."""

from __future__ import annotations

import os
from importlib import import_module
from urllib.parse import urlparse

import click
import uvicorn
from dotenv import load_dotenv

from app.operator_cli.common import CliState, OutputGroup
from app.operator_cli.contract import contract_group
from app.operator_cli.database import database_group
from app.operator_cli.development import development_group
from app.operator_cli.entitlements import entitlements_group
from app.operator_cli.health import doctor_command
from app.operator_cli.jobs import jobs_group
from app.operator_cli.maintenance import maintenance_group
from app.operator_cli.usage import usage_group
from app.operator_cli.users import users_group
from app.operator_cli.verify import verify_group

LOCAL_DATABASE_URL = (
    "postgresql://scholens_app:replace-with-local-runtime-password@"
    "127.0.0.1:55432/sanchezcloud"
)


def require_local_database_url(database_url: str) -> None:
    """Reject any target outside the registered shared-local PostgreSQL."""
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
            "Scholens local startup requires PostgreSQL at 127.0.0.1:55432/sanchezcloud"
        )


def require_local_server_address(host: str, port: int) -> None:
    """Reject stale or externally exposed local-listener settings."""
    if host != "127.0.0.1" or port != 7301:
        raise ValueError("Scholens local API must listen on 127.0.0.1:7301")


def serve_application() -> None:
    """Validate the shared-local target and start the development API."""
    database_url = os.getenv("DATABASE_URL", LOCAL_DATABASE_URL)
    require_local_database_url(database_url)
    require_local_database_url(os.getenv("AUTH_DATABASE_URL", database_url))
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7301"))
    require_local_server_address(host, port)
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )


@click.group(cls=OutputGroup)
@click.version_option(package_name="scholens")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Operate and diagnose a Scholens deployment."""
    load_dotenv()
    # CLI processes do not import the FastAPI composition root. Register the
    # complete SQLAlchemy model graph before any leaf command opens a session.
    import_module("app.database.models")
    ctx.obj = CliState(json_output=bool(ctx.meta.get("scholens_json_output")))


@cli.command("serve")
def serve_command() -> None:
    """Start the fixed-address local development API."""
    serve_application()


cli.add_command(doctor_command)
cli.add_command(users_group)
cli.add_command(entitlements_group)
cli.add_command(usage_group)
cli.add_command(jobs_group)
cli.add_command(database_group)
cli.add_command(contract_group)
cli.add_command(verify_group)
cli.add_command(maintenance_group)
cli.add_command(development_group)


__all__ = [
    "LOCAL_DATABASE_URL",
    "cli",
    "require_local_database_url",
    "require_local_server_address",
    "serve_application",
]
