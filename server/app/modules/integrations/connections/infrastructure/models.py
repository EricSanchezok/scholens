"""Persistence for user-owned external integration credentials."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.infrastructure.persistence import Base
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class IntegrationCredentialRow(Base):
    """Common encrypted credential columns; concrete stores own their tables."""

    __abstract__ = True

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    credential_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    credential_revision: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)


class IntegrationConnection(IntegrationCredentialRow):
    __tablename__ = "integration_connections"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('mineru', 'anysearch', 'tavily', 'exa', 'firecrawl', 'openalex', 'zotero')",
            name="ck_integration_connections_provider",
        ),
        {"schema": "scholens"},
    )


class ModelConnection(IntegrationCredentialRow):
    __tablename__ = "model_connections"
    __table_args__ = ({"schema": "scholens"},)
