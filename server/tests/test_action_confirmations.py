from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.modules.action_confirmations.application import (
    ActionConfirmations,
    confirmation_digest,
    hash_confirmation_value,
)
from app.modules.action_confirmations.contracts import (
    ActionConfirmationRecord,
    ActionImpact,
)
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    McpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, JsonValue


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class MemoryConfirmationStore:
    def __init__(self) -> None:
        self.records: dict[str, ActionConfirmationRecord] = {}
        self.impacts: dict[str, JsonValue] = {}

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
        del now
        self.records[token_hash] = ActionConfirmationRecord(
            actor_id=actor_id,
            credential_kind=credential_kind,
            credential_reference=credential_reference,
            action=action,
            arguments_hash=arguments_hash,
            state_fingerprint=state_fingerprint,
            consumed_at=None,
            expires_at=expires_at,
        )
        self.impacts[token_hash] = impact

    def lock_by_token_hash(self, *, token_hash: str) -> ActionConfirmationRecord | None:
        return self.records.get(token_hash)

    def mark_consumed(self, *, token_hash: str, now: datetime) -> None:
        self.records[token_hash] = replace(self.records[token_hash], consumed_at=now)

    def delete_expired(self, *, now: datetime) -> None:
        expired = [
            token_hash
            for token_hash, record in self.records.items()
            if record.expires_at <= now
        ]
        for token_hash in expired:
            del self.records[token_hash]
            self.impacts.pop(token_hash, None)


def _actor(actor_id: int = 7) -> Actor:
    return Actor(
        id=actor_id,
        email=f"researcher-{actor_id}@example.com",
        status="active",
        email_verified=True,
    )


def _operation(
    credential_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
) -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.AGENT,
        origin=McpOrigin(
            request=RequestReference(uuid4()),
            mcp_session_ref="1" * 64,
            mcp_request_ref="2" * 64,
        ),
        credential=CredentialRef(CredentialKind.ACCESS_KEY, credential_id),
    )


def _impact() -> ActionImpact:
    return ActionImpact(
        title="Delete Project",
        summary="Delete the bound research Project.",
        consequences=["Project-scoped annotations are removed."],
        affected_resources=["project:example"],
    )


def test_confirmation_is_hashed_bound_and_single_use() -> None:
    clock = FixedClock(datetime(2026, 8, 16, 9, 0, tzinfo=UTC))
    store = MemoryConfirmationStore()
    confirmations = ActionConfirmations(repository=store, clock=clock)
    actor = _actor()
    operation = _operation()
    arguments_hash = confirmation_digest({"project_id": "example"})
    state_fingerprint = confirmation_digest({"revision": 3})

    challenge = confirmations.issue(
        actor=actor,
        operation=operation,
        action="delete_project",
        arguments_hash=arguments_hash,
        state_fingerprint=state_fingerprint,
        impact=_impact(),
    )
    token_hash = hash_confirmation_value(challenge.confirmation_token)

    assert challenge.expires_at == clock.value + timedelta(minutes=10)
    assert challenge.confirmation_token not in store.records
    assert token_hash in store.records
    confirmations.consume(
        actor=actor,
        operation=operation,
        token=challenge.confirmation_token,
        action="delete_project",
        arguments_hash=arguments_hash,
        state_fingerprint=state_fingerprint,
    )
    assert store.records[token_hash].consumed_at == clock.value

    with pytest.raises(AppError) as reused:
        confirmations.consume(
            actor=actor,
            operation=operation,
            token=challenge.confirmation_token,
            action="delete_project",
            arguments_hash=arguments_hash,
            state_fingerprint=state_fingerprint,
        )
    assert reused.value.code == "confirmation_consumed"


@pytest.mark.parametrize(
    ("actor", "operation", "arguments_hash", "state_fingerprint", "code"),
    [
        (_actor(8), _operation(), "arguments", "state", "confirmation_mismatch"),
        (
            _actor(),
            _operation("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            "arguments",
            "state",
            "confirmation_mismatch",
        ),
        (_actor(), _operation(), "changed", "state", "confirmation_mismatch"),
        (_actor(), _operation(), "arguments", "changed", "confirmation_stale"),
    ],
)
def test_confirmation_rejects_changed_binding_or_state(
    actor: Actor,
    operation: OperationContext,
    arguments_hash: str,
    state_fingerprint: str,
    code: str,
) -> None:
    clock = FixedClock(datetime(2026, 8, 16, 9, 0, tzinfo=UTC))
    store = MemoryConfirmationStore()
    confirmations = ActionConfirmations(repository=store, clock=clock)
    challenge = confirmations.issue(
        actor=_actor(),
        operation=_operation(),
        action="delete_project",
        arguments_hash="arguments",
        state_fingerprint="state",
        impact=_impact(),
    )

    with pytest.raises(AppError) as rejected:
        confirmations.consume(
            actor=actor,
            operation=operation,
            token=challenge.confirmation_token,
            action="delete_project",
            arguments_hash=arguments_hash,
            state_fingerprint=state_fingerprint,
        )
    assert rejected.value.code == code


def test_confirmation_rejects_expired_challenge() -> None:
    clock = FixedClock(datetime(2026, 8, 16, 9, 0, tzinfo=UTC))
    store = MemoryConfirmationStore()
    confirmations = ActionConfirmations(repository=store, clock=clock)
    actor = _actor()
    operation = _operation()
    challenge = confirmations.issue(
        actor=actor,
        operation=operation,
        action="delete_project",
        arguments_hash="arguments",
        state_fingerprint="state",
        impact=_impact(),
    )
    clock.value = challenge.expires_at

    with pytest.raises(AppError) as expired:
        confirmations.consume(
            actor=actor,
            operation=operation,
            token=challenge.confirmation_token,
            action="delete_project",
            arguments_hash="arguments",
            state_fingerprint="state",
        )
    assert expired.value.code == "confirmation_expired"
