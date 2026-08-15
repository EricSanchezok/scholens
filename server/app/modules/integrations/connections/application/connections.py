"""User-owned integration connection use cases."""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from app.modules.integrations.connections.application.contracts import (
    IntegrationConnectionResponse,
    IntegrationConnectionState,
    IntegrationListResponse,
)
from app.modules.integrations.connections.application.ports import (
    IntegrationCredential,
    IntegrationCredentialCipher,
    IntegrationCredentialState,
    IntegrationGateway,
    IntegrationRecord,
    UnreadableIntegrationCredential,
)
from app.modules.integrations.connections.domain import (
    SEARCH_CONNECTOR_PROVIDERS,
    USER_MANAGED_INTEGRATION_PROVIDERS,
    IntegrationProvider,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, Clock, OperationContext
from app.shared.domain import AppError, FailureKind

INTEGRATION_CONNECTED = OperationAction("integration.connected")
INTEGRATION_ENABLED = OperationAction("integration.enabled")
INTEGRATION_DISABLED = OperationAction("integration.disabled")
INTEGRATION_DISCONNECTED = OperationAction("integration.disconnected")
INTEGRATION_VERIFIED = OperationAction("integration.verified")
INTEGRATION_INVALID = OperationAction("integration.invalid")

IntegrationOutcome = Literal["verified", "invalid", "failed"]
_INVALID_CREDENTIAL_CODES = frozenset(
    {"mineru_credential_invalid", "integration_credentials_invalid"}
)


class Integrations:
    def __init__(
        self,
        *,
        gateway: IntegrationGateway,
        cipher: IntegrationCredentialCipher,
        clock: Clock,
        journal: OperationJournal,
        scholight_configured: bool,
    ) -> None:
        self._gateway = gateway
        self._cipher = cipher
        self._clock = clock
        self._journal = journal
        self._scholight_configured = scholight_configured

    def list(self, *, actor: Actor) -> IntegrationListResponse:
        records = {
            record.provider: record
            for record in self._gateway.list_owned(user_id=actor.id)
        }
        built_in_state: IntegrationConnectionState = (
            "connected" if self._scholight_configured else "disconnected"
        )
        items = [
            IntegrationConnectionResponse(
                provider=IntegrationProvider.SCHOLIGHT,
                category="built_in",
                managed=True,
                state=built_in_state,
                enabled=self._scholight_configured,
            )
        ]
        for provider in USER_MANAGED_INTEGRATION_PROVIDERS:
            record = records.get(provider)
            items.append(
                _response(
                    provider,
                    record,
                    credential_readable=self._credential_readable(
                        user_id=actor.id,
                        provider=provider,
                        record=record,
                    ),
                )
            )
        return IntegrationListResponse(items=items)

    def connect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: IntegrationProvider,
        credential: str,
        verified: bool,
    ) -> IntegrationConnectionResponse:
        _require_user_managed(provider)
        now = self._clock.now()
        record = self._gateway.upsert(
            user_id=actor.id,
            provider=provider,
            credential_ciphertext=self._cipher.encrypt(
                user_id=actor.id,
                provider=provider,
                plaintext=credential,
            ),
            credential_revision=uuid4(),
            configuration={},
            verified_at=now if verified else None,
            now=now,
        )
        self._record_action(
            actor=actor,
            operation=operation,
            action=INTEGRATION_CONNECTED,
            provider=provider,
        )
        return _response(provider, record)

    def set_enabled(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: IntegrationProvider,
        enabled: bool,
        verified: bool,
    ) -> IntegrationConnectionResponse:
        _require_user_managed(provider)
        current = self._gateway.get_owned(
            user_id=actor.id,
            provider=provider,
            lock=True,
        )
        if current is None:
            raise AppError(
                code="integration_not_connected",
                message="Integration is not connected",
                kind=FailureKind.CONFLICT,
            )
        if current.enabled == enabled:
            return _response(provider, current)
        now = self._clock.now()
        updated = self._gateway.set_enabled(
            user_id=actor.id,
            provider=provider,
            enabled=enabled,
            verified_at=now if enabled and verified else current.verified_at,
            now=now,
        )
        self._record_action(
            actor=actor,
            operation=operation,
            action=INTEGRATION_ENABLED if enabled else INTEGRATION_DISABLED,
            provider=provider,
        )
        return _response(provider, updated)

    def disconnect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: IntegrationProvider,
    ) -> None:
        _require_user_managed(provider)
        current = self._gateway.get_owned(
            user_id=actor.id,
            provider=provider,
            lock=True,
        )
        if current is None:
            return
        self._gateway.delete(user_id=actor.id, provider=provider)
        self._record_action(
            actor=actor,
            operation=operation,
            action=INTEGRATION_DISCONNECTED,
            provider=provider,
        )

    def credential(
        self,
        *,
        actor: Actor,
        provider: IntegrationProvider,
        require_enabled: bool = True,
    ) -> IntegrationCredential:
        return self.credential_for_user(
            user_id=actor.id,
            provider=provider,
            require_enabled=require_enabled,
        )

    def credential_for_user(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        require_enabled: bool = True,
    ) -> IntegrationCredential:
        _require_user_managed(provider)
        record = self._gateway.get_owned(user_id=user_id, provider=provider)
        if record is None or (require_enabled and not record.enabled):
            raise AppError(
                code="integration_not_connected",
                message="Integration is not connected and enabled",
                kind=FailureKind.CONFLICT,
            )
        try:
            secret = self._cipher.decrypt(
                user_id=user_id,
                provider=provider,
                ciphertext=record.credential_ciphertext,
            )
        except ValueError:
            if provider is IntegrationProvider.MINERU:
                raise AppError(
                    code="mineru_credential_invalid",
                    message="The connected MinerU credential must be replaced",
                    kind=FailureKind.UNPROCESSABLE,
                    retryable=True,
                    details={"required_integration": provider.value},
                ) from None
            raise AppError(
                code="integration_credentials_unreadable",
                message="Integration credentials could not be read; reconnect it",
                kind=FailureKind.UNAVAILABLE,
            ) from None
        return IntegrationCredential(
            provider=provider,
            secret=secret,
            revision=record.credential_revision,
            updated_at=record.updated_at,
        )

    def require_ready(
        self,
        *,
        actor: Actor,
        provider: IntegrationProvider,
    ) -> None:
        record = self._gateway.get_owned(user_id=actor.id, provider=provider)
        if record is None or not record.enabled:
            raise AppError(
                code=(
                    "mineru_credential_required"
                    if provider is IntegrationProvider.MINERU
                    else "integration_not_connected"
                ),
                message="A connected integration credential is required",
                kind=FailureKind.CONFLICT,
                retryable=True,
                details={"required_integration": provider.value},
            )
        if record.last_error_code in _INVALID_CREDENTIAL_CODES:
            raise AppError(
                code=(
                    "mineru_credential_invalid"
                    if provider is IntegrationProvider.MINERU
                    else "integration_credentials_invalid"
                ),
                message="The connected integration credential is invalid",
                kind=FailureKind.UNPROCESSABLE,
                retryable=True,
                details={"required_integration": provider.value},
            )
        self.credential(actor=actor, provider=provider)

    def _credential_readable(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        record: IntegrationRecord | None,
    ) -> bool:
        if record is None:
            return True
        try:
            self._cipher.decrypt(
                user_id=user_id,
                provider=provider,
                ciphertext=record.credential_ciphertext,
            )
        except ValueError:
            return False
        return True

    def enabled_connector_credentials(
        self,
        *,
        actor: Actor,
    ) -> tuple[IntegrationCredentialState, ...]:
        result: list[IntegrationCredentialState] = []
        for provider in SEARCH_CONNECTOR_PROVIDERS:
            record = self._gateway.get_owned(user_id=actor.id, provider=provider)
            if record is None or not record.enabled:
                continue
            try:
                secret = self._cipher.decrypt(
                    user_id=actor.id,
                    provider=provider,
                    ciphertext=record.credential_ciphertext,
                )
            except ValueError:
                result.append(UnreadableIntegrationCredential(provider))
                continue
            result.append(
                IntegrationCredential(
                    provider=provider,
                    secret=secret,
                    revision=record.credential_revision,
                    updated_at=record.updated_at,
                )
            )
        return tuple(result)

    def record_outcome(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: IntegrationProvider,
        credential_revision: UUID,
        outcome: IntegrationOutcome,
        error_code: str | None = None,
    ) -> bool:
        _require_user_managed(provider)
        now = self._clock.now()
        invalid = outcome == "invalid" or error_code in _INVALID_CREDENTIAL_CODES
        record = self._gateway.record_outcome(
            user_id=actor.id,
            provider=provider,
            credential_revision=credential_revision,
            verified_at=now if outcome == "verified" else None,
            last_used_at=now,
            last_error_code=(error_code or "integration_credentials_invalid")
            if invalid
            else None,
        )
        if record is None:
            return False
        if outcome == "verified" or invalid:
            self._record_action(
                actor=actor,
                operation=operation,
                action=INTEGRATION_VERIFIED
                if outcome == "verified"
                else INTEGRATION_INVALID,
                provider=provider,
            )
        return True

    def _record_action(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        action: OperationAction,
        provider: IntegrationProvider,
    ) -> None:
        self._journal.append(
            actor=actor,
            operation=operation,
            action=action,
            resources=(ResourceRef("integration", provider.value),),
        )


def _require_user_managed(provider: IntegrationProvider) -> None:
    if provider is IntegrationProvider.SCHOLIGHT:
        raise AppError(
            code="integration_managed_by_system",
            message="This integration is managed by Scholens",
            kind=FailureKind.CONFLICT,
        )
    if provider not in USER_MANAGED_INTEGRATION_PROVIDERS:
        raise AppError(
            code="integration_not_supported",
            message="Integration provider is not supported",
            kind=FailureKind.NOT_FOUND,
        )


def _category(provider: IntegrationProvider) -> Literal["parsing", "search"]:
    return "parsing" if provider is IntegrationProvider.MINERU else "search"


def _response(
    provider: IntegrationProvider,
    record: IntegrationRecord | None,
    *,
    credential_readable: bool = True,
) -> IntegrationConnectionResponse:
    if record is None:
        return IntegrationConnectionResponse(
            provider=provider,
            category=_category(provider),
            managed=False,
            state="disconnected",
            enabled=False,
        )
    state: IntegrationConnectionState
    if not credential_readable:
        state = "invalid"
    elif not record.enabled:
        state = "disabled"
    elif record.last_error_code in _INVALID_CREDENTIAL_CODES:
        state = "invalid"
    elif record.verified_at is None:
        state = "connected_unverified"
    else:
        state = "connected"
    return IntegrationConnectionResponse(
        provider=provider,
        category=_category(provider),
        managed=False,
        state=state,
        enabled=record.enabled,
        verified_at=record.verified_at,
        last_used_at=record.last_used_at,
        last_error_code=(
            record.last_error_code
            if credential_readable
            else "integration_credentials_unreadable"
        ),
        updated_at=record.updated_at,
    )
