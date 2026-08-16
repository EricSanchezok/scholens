"""Encrypted persistence for Zotero OAuth state and the unified connection row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.modules.integrations.connections.application.ports import (
    IntegrationCredentialCipher,
    IntegrationRecord,
)
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.integrations.connections.infrastructure.repository import (
    SqlAlchemyIntegrationGateway,
)
from app.modules.integrations.zotero.infrastructure.models import ZoteroOAuthPending
from app.shared.domain import JsonValue
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

PENDING_TTL_MINUTES = 15


@dataclass(frozen=True, slots=True)
class ConnectionUpsert:
    connection: IntegrationRecord
    changed: bool


class ZoteroConnectionRepository:
    def __init__(
        self,
        db: Session,
        *,
        cipher: IntegrationCredentialCipher,
    ) -> None:
        self._db = db
        self._cipher = cipher
        self._connections = SqlAlchemyIntegrationGateway(db)

    def create_pending(
        self,
        *,
        user_id: int,
        oauth_token: str,
        oauth_token_secret: str,
        return_path: str,
        intent: str,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> ZoteroOAuthPending:
        self.delete_pending_for_user(user_id=user_id)
        db_obj = ZoteroOAuthPending(
            user_id=user_id,
            oauth_token=oauth_token,
            oauth_token_secret_ciphertext=self._cipher.encrypt(
                user_id=user_id,
                provider=IntegrationProvider.ZOTERO,
                plaintext=oauth_token_secret,
            ),
            return_path=return_path,
            intent=intent,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=PENDING_TTL_MINUTES),
        )
        self._db.add(db_obj)
        self._db.flush()
        self._db.refresh(db_obj)
        return db_obj

    def get_pending_by_token(self, *, oauth_token: str) -> ZoteroOAuthPending | None:
        return self._db.scalar(
            select(ZoteroOAuthPending)
            .where(ZoteroOAuthPending.oauth_token == oauth_token)
            .with_for_update()
        )

    def pending_secret(self, *, pending: ZoteroOAuthPending) -> str:
        return self._cipher.decrypt(
            user_id=pending.user_id,
            provider=IntegrationProvider.ZOTERO,
            ciphertext=pending.oauth_token_secret_ciphertext,
        )

    def delete_pending(self, *, pending: ZoteroOAuthPending) -> None:
        self._db.delete(pending)
        self._db.flush()

    def delete_pending_for_user(self, *, user_id: int) -> None:
        self._db.execute(
            delete(ZoteroOAuthPending).where(ZoteroOAuthPending.user_id == user_id)
        )
        self._db.flush()

    def upsert_connection(
        self,
        *,
        user_id: int,
        zotero_user_id: str,
        api_key: str,
        now: datetime,
    ) -> ConnectionUpsert:
        current = self.get_by_user_id(user_id=user_id)
        record = self._connections.upsert(
            user_id=user_id,
            provider=IntegrationProvider.ZOTERO,
            credential_ciphertext=self._cipher.encrypt(
                user_id=user_id,
                provider=IntegrationProvider.ZOTERO,
                plaintext=api_key,
            ),
            credential_revision=uuid4(),
            configuration={
                "zotero_user_id": str(zotero_user_id),
                "auto_import_enabled": False,
                "auto_import_library_version": None,
                "last_sync_library_version": None,
            },
            verified_at=now,
            now=now,
        )
        return ConnectionUpsert(connection=record, changed=current != record)

    def get_by_user_id(self, *, user_id: int) -> IntegrationRecord | None:
        return self._connections.get_owned(
            user_id=user_id,
            provider=IntegrationProvider.ZOTERO,
        )

    def credentials(self, *, user_id: int) -> tuple[str, str, UUID] | None:
        record = self.get_by_user_id(user_id=user_id)
        if record is None or not record.enabled:
            return None
        zotero_user_id = record.configuration.get("zotero_user_id")
        if not isinstance(zotero_user_id, str) or not zotero_user_id:
            return None
        api_key = self._cipher.decrypt(
            user_id=user_id,
            provider=IntegrationProvider.ZOTERO,
            ciphertext=record.credential_ciphertext,
        )
        return zotero_user_id, api_key, record.credential_revision

    def credential_revision_is_current(
        self,
        *,
        user_id: int,
        revision: UUID,
    ) -> bool:
        record = self.get_by_user_id(user_id=user_id)
        return (
            record is not None
            and record.enabled
            and record.credential_revision == revision
        )

    def update_configuration(
        self,
        *,
        user_id: int,
        configuration: dict[str, JsonValue],
        now: datetime,
    ) -> IntegrationRecord:
        return self._connections.set_configuration(
            user_id=user_id,
            provider=IntegrationProvider.ZOTERO,
            configuration=configuration,
            now=now,
        )

    def delete_by_user_id(self, *, user_id: int) -> UUID | None:
        connection = self.get_by_user_id(user_id=user_id)
        if connection is None:
            return None
        self._connections.delete(
            user_id=user_id,
            provider=IntegrationProvider.ZOTERO,
        )
        return connection.credential_revision
