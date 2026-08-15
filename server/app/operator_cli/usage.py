"""Resource and provider-reported token usage inspection."""

from __future__ import annotations

from datetime import date
from typing import Any

import click
from sqlalchemy import case, func, select

from app.operator_cli.common import (
    CliState,
    OutputGroup,
    email_callback,
    emit,
    guarded,
)


def _token_rows(
    *,
    email: str | None,
    plan: str | None,
    feature: str | None,
    profile: str | None,
    model: str | None,
    week_start: date | None,
    limit: int,
) -> list[dict[str, object]]:
    from app.database.database import SessionLocal
    from app.database.models import AuthUser, TokenUsageEvent
    from app.modules.billing.infrastructure.quotas import get_user_entitlements
    from app.modules.identity.infrastructure.users import actor_from_auth_user

    dimensions: tuple[Any, ...] = (
        TokenUsageEvent.user_id,
        AuthUser.email,
        TokenUsageEvent.feature,
        TokenUsageEvent.ai_profile,
        TokenUsageEvent.provider,
        TokenUsageEvent.model,
    )
    statement = (
        select(
            *dimensions,
            func.sum(TokenUsageEvent.prompt_tokens),
            func.sum(TokenUsageEvent.completion_tokens),
            func.sum(TokenUsageEvent.reasoning_tokens),
            func.sum(TokenUsageEvent.cache_hit_tokens),
            func.sum(TokenUsageEvent.cache_miss_tokens),
            func.sum(TokenUsageEvent.total_tokens),
            func.sum(case((TokenUsageEvent.status == "unknown", 1), else_=0)),
        )
        .join(AuthUser, AuthUser.id == TokenUsageEvent.user_id)
        .group_by(*dimensions)
        .order_by(func.sum(TokenUsageEvent.total_tokens).desc())
        .limit(limit)
    )
    if email is not None:
        statement = statement.where(AuthUser.email == email)
    if feature is not None:
        statement = statement.where(TokenUsageEvent.feature == feature)
    if profile is not None:
        statement = statement.where(TokenUsageEvent.ai_profile == profile)
    if model is not None:
        statement = statement.where(TokenUsageEvent.model == model)
    if week_start is not None:
        statement = statement.where(TokenUsageEvent.week_start == week_start)

    with SessionLocal() as db:
        raw_rows = db.execute(statement).all()
        users = {
            user.id: user
            for user in db.scalars(
                select(AuthUser).where(
                    AuthUser.id.in_({int(row[0]) for row in raw_rows})
                )
            ).unique()
        }
        rows: list[dict[str, object]] = []
        for row in raw_rows:
            user = users[int(row[0])]
            resolution = get_user_entitlements(db, actor_from_auth_user(user))
            if plan is not None and resolution.plan.value != plan:
                continue
            rows.append(
                {
                    "user_id": row[0],
                    "email": row[1],
                    "plan": resolution.plan.value,
                    "plan_source": resolution.source,
                    "feature": row[2],
                    "profile": row[3],
                    "provider": row[4],
                    "model": row[5],
                    "input_tokens": int(row[6] or 0),
                    "output_tokens": int(row[7] or 0),
                    "reasoning_tokens": int(row[8] or 0),
                    "cache_hit_tokens": int(row[9] or 0),
                    "cache_miss_tokens": int(row[10] or 0),
                    "total_tokens": int(row[11] or 0),
                    "unknown_usage_events": int(row[12] or 0),
                }
            )
    return rows


@click.group("usage", cls=OutputGroup)
def usage_group() -> None:
    """Inspect raw usage without applying a price table."""


@usage_group.command("show")
@click.option("--email", required=True, callback=email_callback)
@click.option(
    "--period",
    type=click.Choice(["current_week", "four_weeks", "twelve_weeks"]),
    default="current_week",
    show_default=True,
)
@click.pass_obj
@guarded
def show_usage(state: CliState, email: str, period: str) -> None:
    from app.database.database import SessionLocal
    from app.modules.billing.application.contracts import UsagePeriod
    from app.modules.billing.infrastructure.quotas import (
        get_user_entitlements,
        get_user_usage_info,
    )
    from app.modules.identity.infrastructure.users import (
        actor_from_auth_user,
        user_repository,
    )

    with SessionLocal() as db:
        user = user_repository.get_by_email(db, email=email)
        if user is None:
            raise click.ClickException(f"No user exists with exact email {email}.")
        actor = actor_from_auth_user(user)
        resolution = get_user_entitlements(db, actor)
        payload = {
            **get_user_usage_info(db, actor, UsagePeriod(period)),
            "email": email,
            "plan_source": resolution.source,
            "grant_expires_at": resolution.grant_expires_at,
            "overrides": dict(resolution.overrides),
        }
    emit(state, payload)


@usage_group.command("report")
@click.option("--email", default=None, callback=email_callback)
@click.option("--plan", type=click.Choice(["basic", "researcher"]), default=None)
@click.option("--feature", default=None)
@click.option("--profile", default=None)
@click.option("--model", default=None)
@click.option("--week-start", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--limit", type=click.IntRange(1, 5000), default=500, show_default=True)
@click.pass_obj
@guarded
def usage_report(
    state: CliState,
    email: str | None,
    plan: str | None,
    feature: str | None,
    profile: str | None,
    model: str | None,
    week_start: Any,
    limit: int,
) -> None:
    rows = _token_rows(
        email=email,
        plan=plan,
        feature=feature,
        profile=profile,
        model=model,
        week_start=week_start.date() if week_start is not None else None,
        limit=limit,
    )
    emit(
        state,
        rows,
        human="\n".join(
            f"{row['email']}\t{row['feature']}\t{row['profile']}\t{row['model']}\t{row['total_tokens']}"
            for row in rows
        ),
    )


__all__ = ["usage_group"]
