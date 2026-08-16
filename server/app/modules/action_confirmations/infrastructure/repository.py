"""PostgreSQL adapter for issuing and consuming confirmation challenges."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.database.models.action_confirmation import ActionConfirmation
from app.modules.action_confirmations.contracts import ActionConfirmationRecord
from app.shared.domain import JsonValue
from sqlalchemy import delete, select
from sqlalchemy.orm import Session


class ActionConfirmationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        actor_id: int,
        credential_kind: str,
        credential_reference: str | None,
        action: str,
        arguments_hash: str,
        state_fingerprint: str,
        impact: JsonValue,
        token_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        self._db.add(
            ActionConfirmation(
                id=uuid4(),
                actor_id=actor_id,
                credential_kind=credential_kind,
                credential_reference=credential_reference,
                action=action,
                arguments_hash=arguments_hash,
                state_fingerprint=state_fingerprint,
                impact=impact,
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
        )
        self._db.flush()

    def lock_by_token_hash(self, *, token_hash: str) -> ActionConfirmationRecord | None:
        model = self._db.scalar(
            select(ActionConfirmation)
            .where(ActionConfirmation.token_hash == token_hash)
            .with_for_update()
        )
        if model is None:
            return None
        return ActionConfirmationRecord(
            actor_id=model.actor_id,
            credential_kind=model.credential_kind,
            credential_reference=model.credential_reference,
            action=model.action,
            arguments_hash=model.arguments_hash,
            state_fingerprint=model.state_fingerprint,
            consumed_at=model.consumed_at,
            expires_at=model.expires_at,
        )

    def mark_consumed(self, *, token_hash: str, now: datetime) -> None:
        model = self._db.scalar(
            select(ActionConfirmation)
            .where(ActionConfirmation.token_hash == token_hash)
            .with_for_update()
        )
        if model is None:
            raise RuntimeError("locked confirmation disappeared before consumption")
        model.consumed_at = now
        model.updated_at = now
        self._db.flush()

    def delete_expired(self, *, now: datetime) -> None:
        self._db.execute(
            delete(ActionConfirmation).where(ActionConfirmation.expires_at <= now)
        )


__all__ = ["ActionConfirmationRepository"]
