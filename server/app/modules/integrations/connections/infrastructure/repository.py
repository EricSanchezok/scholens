"""SQLAlchemy adapter for user-owned integration connections."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.modules.integrations.connections.application.ports import IntegrationRecord
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.integrations.connections.infrastructure.models import (
    IntegrationConnection,
)
from app.shared.domain import JsonValue
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


class SqlAlchemyIntegrationGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_owned(self, *, user_id: int) -> tuple[IntegrationRecord, ...]:
        rows = self._db.scalars(
            select(IntegrationConnection)
            .where(IntegrationConnection.user_id == user_id)
            .order_by(IntegrationConnection.provider)
        ).all()
        return tuple(_record(row) for row in rows)

    def get_owned(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        lock: bool = False,
    ) -> IntegrationRecord | None:
        statement = select(IntegrationConnection).where(
            IntegrationConnection.user_id == user_id,
            IntegrationConnection.provider == provider.value,
        )
        if lock:
            statement = statement.with_for_update()
        row = self._db.scalar(statement)
        return _record(row) if row is not None else None

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
        statement = (
            insert(IntegrationConnection)
            .values(
                user_id=user_id,
                provider=provider.value,
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
            .on_conflict_do_update(
                index_elements=[
                    IntegrationConnection.user_id,
                    IntegrationConnection.provider,
                ],
                set_={
                    "credential_ciphertext": credential_ciphertext,
                    "configuration": configuration,
                    "credential_revision": credential_revision,
                    "enabled": True,
                    "verified_at": verified_at,
                    "last_used_at": None,
                    "last_error_code": None,
                    "updated_at": now,
                },
            )
            .returning(IntegrationConnection)
        )
        row = self._db.scalar(statement)
        assert row is not None
        return _record(row)

    def set_enabled(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        enabled: bool,
        verified_at: datetime | None,
        now: datetime,
    ) -> IntegrationRecord:
        row = self._db.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.user_id == user_id,
                IntegrationConnection.provider == provider.value,
            )
        )
        assert row is not None
        row.enabled = enabled
        row.verified_at = verified_at
        row.last_error_code = None if enabled else row.last_error_code
        row.updated_at = now
        self._db.flush()
        return _record(row)

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
        row = self._db.scalar(
            select(IntegrationConnection)
            .where(
                IntegrationConnection.user_id == user_id,
                IntegrationConnection.provider == provider.value,
                IntegrationConnection.credential_revision == credential_revision,
            )
            .with_for_update()
        )
        if row is None:
            return None
        if verified_at is not None:
            row.verified_at = verified_at
        row.last_used_at = last_used_at
        row.last_error_code = last_error_code
        self._db.flush()
        return _record(row)

    def delete(self, *, user_id: int, provider: IntegrationProvider) -> None:
        self._db.execute(
            delete(IntegrationConnection).where(
                IntegrationConnection.user_id == user_id,
                IntegrationConnection.provider == provider.value,
            )
        )


def _record(row: IntegrationConnection) -> IntegrationRecord:
    return IntegrationRecord(
        user_id=row.user_id,
        provider=IntegrationProvider(row.provider),
        credential_ciphertext=row.credential_ciphertext,
        configuration=dict(row.configuration),
        credential_revision=row.credential_revision,
        enabled=row.enabled,
        verified_at=row.verified_at,
        last_used_at=row.last_used_at,
        last_error_code=row.last_error_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
