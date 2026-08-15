"""Product-owned plan grant and temporary quota override commands."""

from __future__ import annotations

from datetime import UTC, datetime

import click
from sqlalchemy import select

from app.modules.billing.application.entitlement_admin import QUOTA_KEYS
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
    load_actor,
    load_user,
    load_users,
    mutation_payload,
)


@click.group("entitlements", cls=OutputGroup)
def entitlements_group() -> None:
    """Manage grants without changing Stripe subscription state."""


@entitlements_group.command("grant-researcher")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option(
    "--email", "emails", multiple=True, required=True, callback=email_callback
)
@click.option("--days", type=click.IntRange(1, 365), default=365, show_default=True)
@click.option("--reason", required=True)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def grant_researcher(
    state: CliState,
    actor_email: str,
    emails: tuple[str, ...],
    days: int,
    reason: str,
    yes: bool,
) -> None:
    actor_user = load_user(actor_email)
    targets = load_users(emails)
    from app.modules.identity.infrastructure.users import actor_from_auth_user

    target_actors = tuple(actor_from_auth_user(user) for user in targets)
    target_list = ", ".join(user.email for user in targets)
    confirm(f"Grant Researcher for {days} days to {target_list}?", yes=yes)
    operation = cli_operation("entitlements.grant-researcher")
    results = executor().command(
        lambda capabilities: capabilities.entitlement_admin.grant_researcher(
            actor=current_admin(capabilities, actor_user.id),
            operation=operation,
            targets=target_actors,
            days=days,
            reason=reason,
        )
    )
    payload = [
        mutation_payload(
            changed=result.changed,
            email=next(user.email for user in targets if user.id == result.user_id),
            grant_id=result.resource_id,
            days=days,
        )
        for result in results
    ]
    emit(
        state,
        payload,
        human="\n".join(f"{row['email']}: {row['status']}" for row in payload),
    )


@entitlements_group.command("revoke-researcher")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option(
    "--email", "emails", multiple=True, required=True, callback=email_callback
)
@click.option("--reason", required=True)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def revoke_researcher(
    state: CliState,
    actor_email: str,
    emails: tuple[str, ...],
    reason: str,
    yes: bool,
) -> None:
    actor_user = load_user(actor_email)
    targets = load_users(emails)
    from app.modules.identity.infrastructure.users import actor_from_auth_user

    target_actors = tuple(actor_from_auth_user(user) for user in targets)
    target_list = ", ".join(user.email for user in targets)
    confirm(f"Revoke product Researcher grants from {target_list}?", yes=yes)
    results = executor().command(
        lambda capabilities: capabilities.entitlement_admin.revoke_researcher_batch(
            actor=current_admin(capabilities, actor_user.id),
            operation=cli_operation("entitlements.revoke-researcher"),
            targets=target_actors,
            reason=reason,
        )
    )
    payload = [
        mutation_payload(
            changed=result.changed,
            email=next(user.email for user in targets if user.id == result.user_id),
            grant_id=result.resource_id,
        )
        for result in results
    ]
    emit(
        state,
        payload,
        human="\n".join(f"{row['email']}: {row['status']}" for row in payload),
    )


@entitlements_group.command("list")
@click.option("--email", default=None, callback=email_callback)
@click.option("--include-revoked", is_flag=True)
@click.pass_obj
@guarded
def list_entitlements(
    state: CliState,
    email: str | None,
    include_revoked: bool,
) -> None:
    from app.database.database import SessionLocal
    from app.database.models import AccountPlanGrant, AccountQuotaOverride, AuthUser

    user_id = load_user(email).id if email else None
    now = datetime.now(UTC)
    with SessionLocal() as db:
        grant_query = select(AccountPlanGrant)
        override_query = select(AccountQuotaOverride)
        if user_id is not None:
            grant_query = grant_query.where(AccountPlanGrant.user_id == user_id)
            override_query = override_query.where(
                AccountQuotaOverride.user_id == user_id
            )
        if not include_revoked:
            grant_query = grant_query.where(AccountPlanGrant.revoked_at.is_(None))
            override_query = override_query.where(
                AccountQuotaOverride.revoked_at.is_(None)
            )
        grants = list(
            db.scalars(grant_query.order_by(AccountPlanGrant.created_at.desc()))
        )
        overrides = list(
            db.scalars(override_query.order_by(AccountQuotaOverride.created_at.desc()))
        )
        target_ids = {grant.user_id for grant in grants} | {
            override.user_id for override in overrides
        }
        emails: dict[int, str] = {
            int(row[0]): str(row[1])
            for row in db.execute(
                select(AuthUser.id, AuthUser.email).where(AuthUser.id.in_(target_ids))
            ).all()
        }
        rows: list[dict[str, object]] = [
            {
                "kind": "plan_grant",
                "id": grant.id,
                "user_id": grant.user_id,
                "email": emails.get(grant.user_id),
                "plan": grant.plan,
                "expires_at": grant.expires_at,
                "state": (
                    "revoked"
                    if grant.revoked_at is not None
                    else "expired"
                    if grant.expires_at <= now
                    else "active"
                ),
                "reason": grant.reason,
                "revoked_at": grant.revoked_at,
            }
            for grant in grants
        ]
        rows.extend(
            {
                "kind": "quota_override",
                "id": override.id,
                "user_id": override.user_id,
                "email": emails.get(override.user_id),
                "resource_key": override.resource_key,
                "limit_value": override.limit_value,
                "expires_at": override.expires_at,
                "state": (
                    "revoked"
                    if override.revoked_at is not None
                    else "expired"
                    if override.expires_at <= now
                    else "active"
                ),
                "reason": override.reason,
                "revoked_at": override.revoked_at,
            }
            for override in overrides
        )
    emit(state, rows)


@entitlements_group.command("quota-set")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option("--email", required=True, callback=email_callback)
@click.option("--resource", type=click.Choice(sorted(QUOTA_KEYS)), required=True)
@click.option("--value", type=click.IntRange(min=0), required=True)
@click.option("--days", type=click.IntRange(1, 365), default=30, show_default=True)
@click.option("--reason", required=True)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def quota_set(
    state: CliState,
    actor_email: str,
    email: str,
    resource: str,
    value: int,
    days: int,
    reason: str,
    yes: bool,
) -> None:
    actor_user = load_user(actor_email)
    target = load_actor(email)
    confirm(f"Set {email} {resource} to {value} for {days} days?", yes=yes)
    result = executor().command(
        lambda capabilities: capabilities.entitlement_admin.set_quota(
            actor=current_admin(capabilities, actor_user.id),
            operation=cli_operation("entitlements.quota-set"),
            target=target,
            resource_key=resource,
            limit_value=value,
            days=days,
            reason=reason,
        )
    )
    payload = mutation_payload(
        changed=result.changed,
        email=email,
        resource=resource,
        value=value,
        override_id=result.resource_id,
    )
    emit(state, payload, human=f"{email} {resource}: {payload['status']}")


@entitlements_group.command("quota-clear")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option("--email", required=True, callback=email_callback)
@click.option("--resource", type=click.Choice(sorted(QUOTA_KEYS)), required=True)
@click.option("--reason", required=True)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_obj
@guarded
def quota_clear(
    state: CliState,
    actor_email: str,
    email: str,
    resource: str,
    reason: str,
    yes: bool,
) -> None:
    actor_user = load_user(actor_email)
    target = load_actor(email)
    confirm(f"Clear {email} {resource} override?", yes=yes)
    result = executor().command(
        lambda capabilities: capabilities.entitlement_admin.clear_quota(
            actor=current_admin(capabilities, actor_user.id),
            operation=cli_operation("entitlements.quota-clear"),
            target=target,
            resource_key=resource,
            reason=reason,
        )
    )
    payload = mutation_payload(
        changed=result.changed,
        email=email,
        resource=resource,
        override_id=result.resource_id,
    )
    emit(state, payload, human=f"{email} {resource}: {payload['status']}")


__all__ = ["entitlements_group"]
