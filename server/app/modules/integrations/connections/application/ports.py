"""Ports and secret-safe snapshots for user-owned integrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.integrations.connections.domain import IntegrationProvider
from app.shared.domain import JsonValue


@dataclass(frozen=True, slots=True)
class IntegrationRecord:
    user_id: int
    provider: IntegrationProvider
    credential_ciphertext: str = field(repr=False)
    configuration: dict[str, JsonValue]
    credential_revision: UUID
    enabled: bool
    verified_at: datetime | None
    last_used_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IntegrationCredential:
    provider: IntegrationProvider
    secret: str = field(repr=False)
    revision: UUID
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UnreadableIntegrationCredential:
    provider: IntegrationProvider
    code: str = "integration_credentials_unreadable"


IntegrationCredentialState = IntegrationCredential | UnreadableIntegrationCredential


class IntegrationGateway(Protocol):
    def list_owned(self, *, user_id: int) -> tuple[IntegrationRecord, ...]: ...

    def get_owned(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        lock: bool = False,
    ) -> IntegrationRecord | None: ...

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
    ) -> IntegrationRecord: ...

    def set_enabled(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        enabled: bool,
        verified_at: datetime | None,
        now: datetime,
    ) -> IntegrationRecord: ...

    def record_outcome(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        credential_revision: UUID,
        verified_at: datetime | None,
        last_used_at: datetime,
        last_error_code: str | None,
    ) -> IntegrationRecord | None: ...

    def delete(self, *, user_id: int, provider: IntegrationProvider) -> None: ...


class IntegrationCredentialCipher(Protocol):
    def encrypt(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        plaintext: str,
    ) -> str: ...

    def decrypt(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        ciphertext: str,
    ) -> str: ...
