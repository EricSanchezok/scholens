"""Account inspection and audited administrator lifecycle commands."""

from __future__ import annotations

from typing import Any

import click
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

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


def _summary(db: Any, user: Any, *, include_usage: bool) -> dict[str, object]:
    from app.database.models import DurableJob
    from app.modules.billing.application.contracts import UsagePeriod
    from app.modules.billing.infrastructure.quotas import (
        get_user_entitlements,
        get_user_usage_info,
    )
    from app.modules.identity.infrastructure.users import actor_from_auth_user

    actor = actor_from_auth_user(user)
    resolution = get_user_entitlements(db, actor)
    jobs = dict(
        db.execute(
            select(DurableJob.status, func.count(DurableJob.id))
            .where(DurableJob.requested_by_id == user.id)
            .group_by(DurableJob.status)
        ).all()
    )
    payload: dict[str, object] = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "status": str(user.status),
        "email_verified": user.email_verified_at is not None,
        "is_admin": actor.is_admin,
        "is_blocked": actor.is_blocked,
        "plan": resolution.plan.value,
        "plan_source": resolution.source,
        "grant_expires_at": resolution.grant_expires_at,
        "limits": resolution.limits.as_limits(),
        "overrides": dict(resolution.overrides),
        "jobs": jobs,
    }
    if include_usage:
        payload["usage"] = get_user_usage_info(
            db,
            actor,
            UsagePeriod.CURRENT_WEEK,
        )["usage"]
    return payload


@click.group("users", cls=OutputGroup)
def users_group() -> None:
    """Inspect users and manage Scholens administrator state."""


@users_group.command("list")
@click.option(
    "--email", default=None, callback=email_callback, help="Exact email filter."
)
@click.option("--query", default=None, help="Case-insensitive email/name filter.")
@click.option("--status", default=None, help="Exact identity account status.")
@click.option("--plan", type=click.Choice(["basic", "researcher"]), default=None)
@click.option("--limit", type=click.IntRange(1, 500), default=100, show_default=True)
@click.pass_obj
@guarded
def list_users(
    state: CliState,
    email: str | None,
    query: str | None,
    status: str | None,
    plan: str | None,
    limit: int,
) -> None:
    from app.database.database import SessionLocal
    from app.database.models import AuthUser

    with SessionLocal() as db:
        statement = select(AuthUser).options(joinedload(AuthUser.profile))
        if email:
            statement = statement.where(AuthUser.email == email)
        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                AuthUser.email.ilike(pattern) | AuthUser.display_name.ilike(pattern)
            )
        if status:
            statement = statement.where(AuthUser.status == status)
        query_limit = 500 if plan else limit
        users = list(
            db.scalars(statement.order_by(AuthUser.id).limit(query_limit)).unique()
        )
        rows = [_summary(db, user, include_usage=True) for user in users]
        if plan:
            rows = [row for row in rows if row["plan"] == plan][:limit]
    emit(
        state,
        rows,
        human="\n".join(f"{row['id']}\t{row['email']}\t{row['plan']}" for row in rows),
    )


@users_group.command("show")
@click.option("--email", required=True, callback=email_callback)
@click.pass_obj
@guarded
def show_user(state: CliState, email: str) -> None:
    from app.database.database import SessionLocal
    from app.modules.identity.infrastructure.users import user_repository

    with SessionLocal() as db:
        user = user_repository.get_by_email(db, email=email)
        if user is None:
            raise click.ClickException(f"No user exists with exact email {email}.")
        payload = _summary(db, user, include_usage=True)
    emit(state, payload)


@users_group.command("bootstrap-admin")
@click.option("--email", required=True, callback=email_callback)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def bootstrap_admin(state: CliState, email: str, yes: bool) -> None:
    target = load_user(email)
    confirm(f"Bootstrap the first Scholens administrator as {email}?", yes=yes)
    result = executor().command(
        lambda capabilities: capabilities.identity.bootstrap_admin(
            operation=cli_operation("users.bootstrap-admin", system=True),
            user_id=target.id,
        )
    )
    emit(
        state,
        mutation_payload(changed=result.changed, email=email),
        human=result.message,
    )


def _set_admin(
    state: CliState,
    *,
    actor_email: str,
    email: str,
    enabled: bool,
    reason: str,
    yes: bool,
) -> None:
    # Required as an explicit operator acknowledgement. Entitlement reasons
    # are durable business data; identity Journal entries intentionally keep
    # only their safe action/resource projection.
    del reason
    actor_user = load_user(actor_email)
    target = load_user(email)
    verb = "grant" if enabled else "revoke"
    confirm(f"{verb.title()} administrator access for {email}?", yes=yes)
    operation = cli_operation(f"users.{verb}-admin")
    result = executor().command(
        lambda capabilities: capabilities.identity.set_admin(
            actor=current_admin(capabilities, actor_user.id),
            operation=operation,
            user_id=target.id,
            enabled=enabled,
        )
    )
    emit(
        state,
        mutation_payload(changed=result.changed, email=email, enabled=enabled),
        human=result.message,
    )


def _admin_options(function: Any) -> Any:
    function = click.option("--yes", is_flag=True, help="Skip confirmation prompt.")(
        function
    )
    function = click.option("--reason", required=True, help="Auditable change reason.")(
        function
    )
    function = click.option("--email", required=True, callback=email_callback)(function)
    function = click.option("--actor-email", required=True, callback=email_callback)(
        function
    )
    return function


@users_group.command("grant-admin")
@_admin_options
@click.pass_obj
@guarded
def grant_admin(
    state: CliState,
    actor_email: str,
    email: str,
    reason: str,
    yes: bool,
) -> None:
    _set_admin(
        state,
        actor_email=actor_email,
        email=email,
        enabled=True,
        reason=reason,
        yes=yes,
    )


@users_group.command("revoke-admin")
@_admin_options
@click.pass_obj
@guarded
def revoke_admin(
    state: CliState,
    actor_email: str,
    email: str,
    reason: str,
    yes: bool,
) -> None:
    _set_admin(
        state,
        actor_email=actor_email,
        email=email,
        enabled=False,
        reason=reason,
        yes=yes,
    )


def _set_blocked(
    state: CliState,
    *,
    actor_email: str,
    email: str,
    blocked: bool,
    reason: str,
    yes: bool,
) -> None:
    from app.modules.identity.application.contracts import SetUserBlockedRequest

    # See _set_admin: the private Journal does not persist arbitrary prose.
    del reason
    actor_user = load_user(actor_email)
    target = load_user(email)
    verb = "block" if blocked else "unblock"
    confirm(f"{verb.title()} {email}?", yes=yes)
    result = executor().command(
        lambda capabilities: capabilities.identity.set_blocked(
            actor=current_admin(capabilities, actor_user.id),
            operation=cli_operation(f"users.{verb}"),
            user_id=target.id,
            request=SetUserBlockedRequest(blocked=blocked),
        )
    )
    emit(
        state,
        mutation_payload(changed=result.changed, email=email, blocked=blocked),
        human=result.message,
    )


@users_group.command("block")
@_admin_options
@click.pass_obj
@guarded
def block_user(
    state: CliState,
    actor_email: str,
    email: str,
    reason: str,
    yes: bool,
) -> None:
    _set_blocked(
        state,
        actor_email=actor_email,
        email=email,
        blocked=True,
        reason=reason,
        yes=yes,
    )


@users_group.command("unblock")
@_admin_options
@click.pass_obj
@guarded
def unblock_user(
    state: CliState,
    actor_email: str,
    email: str,
    reason: str,
    yes: bool,
) -> None:
    _set_blocked(
        state,
        actor_email=actor_email,
        email=email,
        blocked=False,
        reason=reason,
        yes=yes,
    )


__all__ = ["users_group"]
