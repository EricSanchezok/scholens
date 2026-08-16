from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.integrations.connections.application.connections import Integrations
from app.modules.integrations.connections.application.ports import (
    IntegrationRecord,
    UnreadableIntegrationCredential,
)
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.integrations.connections.infrastructure.secrets import (
    AesGcmIntegrationCredentialCipher,
)
from app.modules.operation_journal.application import OperationJournal
from app.shared.application import Actor, OperationContext
from app.shared.domain import JsonValue
from app.shared.domain import AppError

NOW = datetime(2026, 7, 31, 12, tzinfo=timezone.utc)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Gateway:
    def __init__(self) -> None:
        self.records: dict[tuple[int, IntegrationProvider], IntegrationRecord] = {}

    def list_owned(self, *, user_id: int) -> tuple[IntegrationRecord, ...]:
        return tuple(
            record
            for (owner_id, _), record in self.records.items()
            if owner_id == user_id
        )

    def get_owned(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        lock: bool = False,
    ) -> IntegrationRecord | None:
        del lock
        return self.records.get((user_id, provider))

    def upsert(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        credential_ciphertext: str,
        credential_revision: UUID,
        configuration: dict[str, JsonValue],
        verified_at: datetime | None,
        now: datetime,
    ) -> IntegrationRecord:
        record = IntegrationRecord(
            user_id=user_id,
            provider=provider,
            credential_ciphertext=credential_ciphertext,
            configuration=configuration,
            credential_revision=credential_revision,
            enabled=True,
            verified_at=verified_at,
            last_used_at=None,
            last_error_code=None,
            created_at=now,
            updated_at=now,
        )
        self.records[(user_id, provider)] = record
        return record

    def set_enabled(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        enabled: bool,
        verified_at: datetime | None,
        now: datetime,
    ) -> IntegrationRecord:
        current = self.records[(user_id, provider)]
        record = replace(
            current,
            enabled=enabled,
            verified_at=verified_at,
            updated_at=now,
        )
        self.records[(user_id, provider)] = record
        return record

    def record_outcome(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        credential_revision: UUID,
        verified_at: datetime | None,
        last_used_at: datetime,
        last_error_code: str | None,
    ) -> IntegrationRecord | None:
        current = self.records.get((user_id, provider))
        if current is None or current.credential_revision != credential_revision:
            return None
        record = replace(
            current,
            verified_at=verified_at or current.verified_at,
            last_used_at=last_used_at,
            last_error_code=last_error_code,
        )
        self.records[(user_id, provider)] = record
        return record

    def delete(self, *, user_id: int, provider: IntegrationProvider) -> None:
        self.records.pop((user_id, provider), None)


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _integrations(gateway: _Gateway) -> Integrations:
    cipher = AesGcmIntegrationCredentialCipher(
        base64.urlsafe_b64encode(b"i" * 32).decode()
    )
    return Integrations(
        gateway=gateway,
        cipher=cipher,
        clock=_Clock(),
        journal=MagicMock(spec=OperationJournal),
        scholight_configured=True,
    )


def test_integration_lifecycle_keeps_credentials_server_side() -> None:
    gateway = _Gateway()
    integrations = _integrations(gateway)
    actor = _actor()
    operation = MagicMock(spec=OperationContext)

    initial = integrations.list(actor=actor)
    assert len(initial.items) == 7
    assert initial.items[0].provider is IntegrationProvider.SCHOLIGHT
    assert initial.items[1].provider is IntegrationProvider.MINERU
    assert initial.items[1].state == "disconnected"

    connected = integrations.connect(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.MINERU,
        credential="private-mineru-token",
        verified=False,
    )
    assert connected.state == "connected_unverified"
    assert "private-mineru-token" not in connected.model_dump_json()
    credential = integrations.credential(
        actor=actor,
        provider=IntegrationProvider.MINERU,
    )
    assert credential.secret == "private-mineru-token"

    disabled = integrations.set_enabled(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.MINERU,
        enabled=False,
        verified=False,
    )
    assert disabled.state == "disabled"

    integrations.disconnect(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.MINERU,
    )
    assert gateway.records == {}


def test_search_connection_can_be_marked_verified_at_save() -> None:
    result = _integrations(_Gateway()).connect(
        actor=_actor(),
        operation=MagicMock(spec=OperationContext),
        provider=IntegrationProvider.EXA,
        credential="private-search-key",
        verified=True,
    )

    assert result.state == "connected"
    assert result.verified_at == NOW


def test_openalex_connection_is_user_owned_and_never_listed_as_mcp_credential() -> None:
    gateway = _Gateway()
    integrations = _integrations(gateway)
    operation = MagicMock(spec=OperationContext)
    first = _actor(7)
    second = _actor(8)

    connected = integrations.connect(
        actor=first,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        credential="private-openalex-key",
        verified=True,
    )

    assert connected.state == "connected"
    assert "private-openalex-key" not in connected.model_dump_json()
    assert (
        integrations.credential(
            actor=first,
            provider=IntegrationProvider.OPENALEX,
        ).secret
        == "private-openalex-key"
    )
    with pytest.raises(AppError) as raised:
        integrations.credential(
            actor=second,
            provider=IntegrationProvider.OPENALEX,
        )
    assert raised.value.code == "openalex_credential_required"
    assert integrations.enabled_connector_credentials(actor=first) == ()


def test_unreadable_connector_credential_is_reported_without_ciphertext() -> None:
    gateway = _Gateway()
    gateway.records[(7, IntegrationProvider.TAVILY)] = IntegrationRecord(
        user_id=7,
        provider=IntegrationProvider.TAVILY,
        credential_ciphertext="v1.tampered",
        configuration={},
        credential_revision=uuid4(),
        enabled=True,
        verified_at=NOW,
        last_used_at=None,
        last_error_code=None,
        created_at=NOW,
        updated_at=NOW,
    )

    states = _integrations(gateway).enabled_connector_credentials(actor=_actor())

    assert states == (UnreadableIntegrationCredential(IntegrationProvider.TAVILY),)


def test_unreadable_mineru_credential_requires_safe_reconnection() -> None:
    gateway = _Gateway()
    gateway.records[(7, IntegrationProvider.MINERU)] = IntegrationRecord(
        user_id=7,
        provider=IntegrationProvider.MINERU,
        credential_ciphertext="v1.tampered.private-diagnostic",
        configuration={},
        credential_revision=uuid4(),
        enabled=True,
        verified_at=NOW,
        last_used_at=None,
        last_error_code=None,
        created_at=NOW,
        updated_at=NOW,
    )
    integrations = _integrations(gateway)

    projection = integrations.list(actor=_actor()).items[1]

    assert projection.state == "invalid"
    assert projection.last_error_code == "integration_credentials_unreadable"
    assert "private-diagnostic" not in projection.model_dump_json()

    with pytest.raises(AppError) as raised:
        integrations.require_ready(
            actor=_actor(),
            provider=IntegrationProvider.MINERU,
        )

    assert raised.value.code == "mineru_credential_invalid"
    assert raised.value.retryable is True
    assert raised.value.details == {"required_integration": "mineru"}
    assert raised.value.__cause__ is None
    assert "private-diagnostic" not in str(raised.value)


def test_stale_provider_outcome_cannot_mutate_replaced_credential() -> None:
    gateway = _Gateway()
    integrations = _integrations(gateway)
    actor = _actor()
    operation = MagicMock(spec=OperationContext)
    integrations.connect(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        credential="private-openalex-key",
        verified=True,
    )
    current = gateway.records[(actor.id, IntegrationProvider.OPENALEX)]

    changed = integrations.record_outcome(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        credential_revision=uuid4(),
        outcome="invalid",
        error_code="openalex_credential_invalid",
    )

    assert changed is False
    assert gateway.records[(actor.id, IntegrationProvider.OPENALEX)] == current


def test_stale_probe_cannot_reenable_replaced_credential() -> None:
    gateway = _Gateway()
    integrations = _integrations(gateway)
    actor = _actor()
    operation = MagicMock(spec=OperationContext)
    integrations.connect(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        credential="old-openalex-key",
        verified=True,
    )
    stale_revision = gateway.records[
        (actor.id, IntegrationProvider.OPENALEX)
    ].credential_revision
    integrations.connect(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        credential="replacement-openalex-key",
        verified=True,
    )
    integrations.set_enabled(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        enabled=False,
        verified=False,
    )
    current = gateway.records[(actor.id, IntegrationProvider.OPENALEX)]

    result = integrations.set_enabled(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        enabled=True,
        verified=True,
        expected_credential_revision=stale_revision,
    )

    assert result.enabled is False
    assert gateway.records[(actor.id, IntegrationProvider.OPENALEX)] == current


def test_invalid_openalex_revision_is_blocked_before_decryption() -> None:
    gateway = _Gateway()
    integrations = _integrations(gateway)
    actor = _actor()
    operation = MagicMock(spec=OperationContext)
    integrations.connect(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        credential="private-openalex-key",
        verified=True,
    )
    revision = gateway.records[
        (actor.id, IntegrationProvider.OPENALEX)
    ].credential_revision
    integrations.record_outcome(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.OPENALEX,
        credential_revision=revision,
        outcome="invalid",
        error_code="openalex_credential_invalid",
    )

    with pytest.raises(AppError) as raised:
        integrations.credential(
            actor=actor,
            provider=IntegrationProvider.OPENALEX,
        )

    assert raised.value.code == "openalex_credential_invalid"
    assert raised.value.details == {"required_integration": "openalex"}


def test_current_provider_outcome_marks_connection_verified_or_invalid() -> None:
    gateway = _Gateway()
    integrations = _integrations(gateway)
    actor = _actor()
    operation = MagicMock(spec=OperationContext)
    integrations.connect(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.MINERU,
        credential="private-mineru-token",
        verified=False,
    )
    revision = gateway.records[
        (actor.id, IntegrationProvider.MINERU)
    ].credential_revision

    assert integrations.record_outcome(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.MINERU,
        credential_revision=revision,
        outcome="verified",
    )
    assert integrations.list(actor=actor).items[1].state == "connected"

    assert integrations.record_outcome(
        actor=actor,
        operation=operation,
        provider=IntegrationProvider.MINERU,
        credential_revision=revision,
        outcome="invalid",
        error_code="mineru_credential_invalid",
    )
    assert integrations.list(actor=actor).items[1].state == "invalid"
