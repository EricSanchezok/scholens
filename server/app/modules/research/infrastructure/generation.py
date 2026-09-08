"""Quota and distributed-concurrency adapters for Research generation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    ai_limit_app_error,
    enforce_rate_limit,
    release_concurrency_by_id,
)
from app.modules.integrations.connections.infrastructure.deepseek import (
    require_deepseek_key,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


class SqlGenerationEntitlements:
    def __init__(self, db: Session) -> None:
        self._db = db

    def require_ai_connection(self, *, actor: Actor) -> None:
        require_deepseek_key(self._db, user_id=actor.id)


class RedisGenerationCapacity:
    async def enforce_rate(
        self,
        *,
        actor: Actor,
        client_ip: str,
        feature: Literal["audio", "data_table"],
    ) -> None:
        try:
            await enforce_rate_limit(
                user_id=actor.id,
                ip_address=client_ip,
                feature=feature,
            )
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="AI request limit exceeded",
            ) from None

    async def acquire_audio(self, *, actor: Actor, operation_id: UUID) -> None:
        try:
            await acquire_concurrency(
                user_id=actor.id,
                category="background",
                operation_id=str(operation_id),
            )
            try:
                await acquire_concurrency(
                    user_id=actor.id,
                    category="audio",
                    operation_id=str(operation_id),
                )
            except Exception:
                await self.release_background(actor=actor, operation_id=operation_id)
                raise
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="AI request limit exceeded",
            ) from None

    async def acquire_background(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
    ) -> None:
        try:
            await acquire_concurrency(
                user_id=actor.id,
                category="background",
                operation_id=str(operation_id),
            )
        except AILimitExceeded as exc:
            raise ai_limit_app_error(
                exc,
                exceeded_message="AI request limit exceeded",
            ) from None

    async def release_audio(self, *, actor: Actor, operation_id: UUID) -> None:
        await release_concurrency_by_id(
            user_id=actor.id,
            category="audio",
            operation_id=str(operation_id),
        )
        await self.release_background(actor=actor, operation_id=operation_id)

    async def release_background(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
    ) -> None:
        await release_concurrency_by_id(
            user_id=actor.id,
            category="background",
            operation_id=str(operation_id),
        )
