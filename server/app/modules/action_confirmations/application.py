"""Issue and consume state-bound confirmation challenges."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta

from app.modules.action_confirmations.contracts import (
    ActionConfirmationStore,
    ActionImpact,
    ConfirmationChallenge,
)
from app.shared.application import Actor, Clock, ConversationOrigin, OperationContext
from app.shared.application.json_values import normalize_json_value
from app.shared.domain import AppError, FailureKind, JsonValue
from pydantic import TypeAdapter

CONFIRMATION_TTL = timedelta(minutes=10)
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def hash_confirmation_value(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def confirmation_digest(value: object) -> str:
    """Return one canonical digest for confirmation arguments or live state."""
    normalized = normalize_json_value(value)
    return hashlib.sha256(
        json.dumps(
            normalized,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def credential_binding(operation: OperationContext) -> tuple[str, str | None]:
    credential = operation.credential
    kind = credential.kind.value if credential is not None else "none"
    if credential is not None and credential.credential_id is not None:
        return kind, credential.credential_id
    if isinstance(operation.origin, ConversationOrigin):
        return kind, f"conversation:{operation.origin.conversation_id}"
    return kind, operation.origin.kind


class ActionConfirmations:
    def __init__(
        self,
        *,
        repository: ActionConfirmationStore,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def issue(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        action: str,
        arguments_hash: str,
        state_fingerprint: str,
        impact: ActionImpact,
    ) -> ConfirmationChallenge:
        now = self._clock.now()
        token = secrets.token_urlsafe(32)
        expires_at = now + CONFIRMATION_TTL
        credential_kind, credential_reference = credential_binding(operation)
        self._repository.delete_expired(now=now)
        self._repository.create(
            actor_id=actor.id,
            credential_kind=credential_kind,
            credential_reference=credential_reference,
            action=action,
            arguments_hash=arguments_hash,
            state_fingerprint=state_fingerprint,
            impact=_JSON_VALUE.validate_python(impact.model_dump(mode="json")),
            token_hash=hash_confirmation_value(token),
            expires_at=expires_at,
            now=now,
        )
        return ConfirmationChallenge(
            confirmation_token=token,
            expires_at=expires_at,
            impact=impact,
        )

    def consume(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        token: str,
        action: str,
        arguments_hash: str,
        state_fingerprint: str,
    ) -> None:
        now = self._clock.now()
        record = self._repository.lock_by_token_hash(
            token_hash=hash_confirmation_value(token)
        )
        if record is None:
            raise AppError(
                code="confirmation_invalid",
                message="The confirmation token is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        credential_kind, credential_reference = credential_binding(operation)
        if (
            record.actor_id != actor.id
            or record.credential_kind != credential_kind
            or record.credential_reference != credential_reference
            or record.action != action
            or record.arguments_hash != arguments_hash
        ):
            raise AppError(
                code="confirmation_mismatch",
                message="The confirmation token does not match this action",
                kind=FailureKind.PERMISSION_DENIED,
            )
        if record.consumed_at is not None:
            raise AppError(
                code="confirmation_consumed",
                message="The confirmation token was already used",
                kind=FailureKind.CONFLICT,
            )
        if record.expires_at <= now:
            raise AppError(
                code="confirmation_expired",
                message="The confirmation token expired",
                kind=FailureKind.CONFLICT,
            )
        if record.state_fingerprint != state_fingerprint:
            raise AppError(
                code="confirmation_stale",
                message="The resource changed after the impact preview was created",
                kind=FailureKind.CONFLICT,
            )
        self._repository.mark_consumed(
            token_hash=hash_confirmation_value(token), now=now
        )


__all__ = [
    "ActionConfirmations",
    "CONFIRMATION_TTL",
    "credential_binding",
    "confirmation_digest",
    "hash_confirmation_value",
]
