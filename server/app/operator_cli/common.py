"""Shared CLI validation, output, and application execution helpers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from functools import wraps
from typing import Any, Callable, NoReturn, ParamSpec, TypeVar, cast
from uuid import UUID, uuid4

import click
from alembic.util.exc import CommandError
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.shared.application import (
    Actor,
    CliOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError

P = ParamSpec("P")
R = TypeVar("R")
_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_URL_CREDENTIAL = re.compile(r"(://[^\s:/@]+:)[^\s@]+(@)")


@dataclass(slots=True)
class CliState:
    json_output: bool = False


def _json_output_callback(
    context: click.Context,
    _parameter: click.Parameter,
    value: bool,
) -> None:
    if not value:
        return
    root = context.find_root()
    if isinstance(root.obj, CliState):
        root.obj.json_output = True
    else:
        root.meta["scholens_json_output"] = True


class OutputCommand(click.Command):
    """Click command that accepts ``--json`` in its natural leaf position."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        params = list(kwargs.pop("params", ()))
        params.append(
            click.Option(
                ["--json"],
                is_flag=True,
                expose_value=False,
                callback=_json_output_callback,
                help="Emit machine-readable JSON.",
            )
        )
        kwargs["params"] = params
        super().__init__(*args, **kwargs)


class OutputGroup(click.Group):
    """Command group whose direct commands all inherit stable JSON output."""

    command_class = OutputCommand

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        params = list(kwargs.pop("params", ()))
        params.append(
            click.Option(
                ["--json"],
                is_flag=True,
                expose_value=False,
                callback=_json_output_callback,
                help="Emit machine-readable JSON.",
            )
        )
        kwargs["params"] = params
        super().__init__(*args, **kwargs)


def json_default(value: object) -> object:
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "value"):
        return getattr(value, "value")
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def emit(state: CliState, payload: object, *, human: str | None = None) -> None:
    if state.json_output:
        click.echo(json.dumps(payload, default=json_default, sort_keys=True))
        return
    if human is not None:
        click.echo(human)
        return
    if isinstance(payload, list):
        for item in payload:
            click.echo(json.dumps(item, default=json_default, sort_keys=True))
        return
    click.echo(json.dumps(payload, default=json_default, indent=2, sort_keys=True))


def safe_error_detail(error: object) -> str:
    """Remove URL passwords from operator-facing dependency failures."""
    return _URL_CREDENTIAL.sub(r"\1***\2", str(error))


def _raise_command_error(*, code: str, message: str) -> NoReturn:
    context = click.get_current_context(silent=True)
    state = context.find_root().obj if context is not None else None
    if isinstance(state, CliState) and state.json_output:
        click.echo(
            json.dumps(
                {"ok": False, "error": {"code": code, "message": message}},
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(1)
    raise click.ClickException(f"{code}: {message}")


def guarded(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except AppError as exc:
            _raise_command_error(code=exc.code, message=exc.message)
        except click.ClickException as exc:
            _raise_command_error(code="command_failed", message=safe_error_detail(exc))
        except (
            CommandError,
            SQLAlchemyError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            _raise_command_error(
                code="command_failed",
                message=safe_error_detail(exc),
            )

    return wrapped


def normalize_email(value: str) -> str:
    try:
        return str(_EMAIL_ADAPTER.validate_python(value)).lower()
    except ValidationError as exc:
        raise click.BadParameter("must be a complete email address") from exc


def email_callback(
    _context: click.Context,
    _parameter: click.Parameter,
    value: str | tuple[str, ...] | None,
) -> str | tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, tuple):
        return tuple(normalize_email(item) for item in value)
    return normalize_email(value)


def load_user(email: str) -> Any:
    from app.database.database import SessionLocal
    from app.modules.identity.infrastructure.users import user_repository

    with SessionLocal() as db:
        user = user_repository.get_by_email(db, email=email)
        if user is None:
            raise click.ClickException(f"No user exists with exact email {email}.")
        db.expunge(user)
        return user


def load_actor(email: str) -> Actor:
    from app.modules.identity.infrastructure.users import actor_from_auth_user

    return actor_from_auth_user(load_user(email))


def load_users(emails: tuple[str, ...]) -> tuple[Any, ...]:
    normalized = tuple(dict.fromkeys(emails))
    return tuple(load_user(email) for email in normalized)


def executor() -> Any:
    from app.operator_cli.capabilities import create_operator_executor

    return create_operator_executor()


def cli_operation(command_name: str, *, system: bool = False) -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=(OperationInitiator.SYSTEM if system else OperationInitiator.USER),
        origin=CliOrigin(command_name=command_name, invocation_id=uuid4()),
        credential=None,
    )


def current_admin(capabilities: Any, actor_id: int) -> Actor:
    return cast(Actor, capabilities.identity.lock_current_admin(actor_id))


def confirm(message: str, *, yes: bool) -> None:
    if not yes:
        click.confirm(message, abort=True)


def mutation_payload(*, changed: bool, **values: object) -> dict[str, object]:
    return {
        "status": "changed" if changed else "unchanged",
        "changed": changed,
        **values,
    }


__all__ = [
    "CliState",
    "OutputCommand",
    "OutputGroup",
    "cli_operation",
    "confirm",
    "current_admin",
    "email_callback",
    "emit",
    "executor",
    "guarded",
    "json_default",
    "load_actor",
    "load_user",
    "load_users",
    "mutation_payload",
    "normalize_email",
    "safe_error_detail",
]
