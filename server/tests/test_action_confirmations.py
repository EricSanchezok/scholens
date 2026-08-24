from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

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
from pydantic import BaseModel


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


class ConfirmationStateKind(StrEnum):
    PROJECT = "project"


class ConfirmationStateModel(BaseModel):
    id: UUID
    updated_at: datetime
    kind: ConfirmationStateKind


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            {"project_id": "example"},
            "2dad970e6bb0c8122308e99ebf340a86b0711eeb775f75f7337c6394e6c8e1dc",
        ),
        (
            {"revision": 3},
            "59adfccabbcc7c0fdfae1b37b93f057a55f041e04476756bda7c37d565d1bf1c",
        ),
        (
            ConfirmationStateModel(
                id=UUID("11111111-1111-1111-1111-111111111111"),
                updated_at=datetime(2026, 8, 24, tzinfo=UTC),
                kind=ConfirmationStateKind.PROJECT,
            ),
            "f2b0ca00892ddb2440c7e18be44739bb0992aa84f3a884093e06fc455d371e9e",
        ),
    ],
)
def test_confirmation_digest_preserves_existing_golden_values(
    value: object,
    expected: str,
) -> None:
    assert confirmation_digest(value) == expected


@pytest.mark.parametrize(
    "state",
    [
        pytest.param(
            {
                "project": ConfirmationStateModel(
                    id=UUID("11111111-1111-1111-1111-111111111111"),
                    updated_at=datetime(2026, 8, 24, tzinfo=UTC),
                    kind=ConfirmationStateKind.PROJECT,
                ),
                "email": "collaborator@example.com",
            },
            id="create-project-invitation",
        ),
        pytest.param(
            {
                "project": ConfirmationStateModel(
                    id=UUID("11111111-1111-1111-1111-111111111111"),
                    updated_at=datetime(2026, 8, 24, tzinfo=UTC),
                    kind=ConfirmationStateKind.PROJECT,
                ),
                "target": ConfirmationStateModel(
                    id=UUID("22222222-2222-2222-2222-222222222222"),
                    updated_at=datetime(2026, 8, 24, 1, tzinfo=UTC),
                    kind=ConfirmationStateKind.PROJECT,
                ),
            },
            id="transfer-project-ownership",
        ),
        pytest.param(
            {
                "project": ConfirmationStateModel(
                    id=UUID("11111111-1111-1111-1111-111111111111"),
                    updated_at=datetime(2026, 8, 24, tzinfo=UTC),
                    kind=ConfirmationStateKind.PROJECT,
                ),
                "threads": [
                    ConfirmationStateModel(
                        id=UUID("33333333-3333-3333-3333-333333333333"),
                        updated_at=datetime(2026, 8, 24, 2, tzinfo=UTC),
                        kind=ConfirmationStateKind.PROJECT,
                    )
                ],
            },
            id="remove-paper-from-project",
        ),
        pytest.param(
            [
                ConfirmationStateModel(
                    id=UUID("44444444-4444-4444-4444-444444444444"),
                    updated_at=datetime(2026, 8, 24, 3, tzinfo=UTC),
                    kind=ConfirmationStateKind.PROJECT,
                )
            ],
            id="remove-library-papers",
        ),
    ],
)
def test_confirmation_digest_supports_nested_live_state_models(
    state: object,
) -> None:
    first = confirmation_digest(state)
    second = confirmation_digest(state)

    assert first == second
    assert len(first) == 64


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
