"""Short-lived, single-use confirmation challenge ledger."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.shared.domain import JsonValue
from app.shared.infrastructure.persistence import Base
from sqlalchemy import BigInteger, CHAR, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class ActionConfirmation(Base):
    __tablename__ = "action_confirmations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    state_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    impact: Mapped[JsonValue] = mapped_column(JSONB, nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


Index(
    "ix_action_confirmations_expiry",
    ActionConfirmation.expires_at,
    ActionConfirmation.consumed_at,
)


__all__ = ["ActionConfirmation"]
