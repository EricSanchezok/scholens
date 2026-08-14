"""Persistence model for user-owned translation preferences."""

from __future__ import annotations

from app.shared.infrastructure.persistence import Base
import uuid

from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column


class TranslationPreference(Base):
    __tablename__ = "translation_preferences"
    __table_args__ = (
        CheckConstraint(
            "source_language = 'auto' OR "
            "(length(source_language) BETWEEN 2 AND 35 "
            "AND source_language = btrim(source_language))",
            name="ck_translation_preferences_source_language",
        ),
        CheckConstraint(
            "length(target_language) BETWEEN 2 AND 35 "
            "AND target_language = btrim(target_language)",
            name="ck_translation_preferences_language",
        ),
        CheckConstraint(
            "custom_instructions IS NULL "
            "OR (length(custom_instructions) BETWEEN 1 AND 2000 "
            "AND custom_instructions = btrim(custom_instructions))",
            name="ck_translation_preferences_instructions",
        ),
        {"schema": "scholens"},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_language: Mapped[str] = mapped_column(
        String(35), nullable=False, default="auto", server_default="auto"
    )
    target_language: Mapped[str] = mapped_column(String(35), nullable=False)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_translate_selection: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )


class TranslationResult(Base):
    __tablename__ = "translation_results"
    __table_args__ = (
        CheckConstraint(
            "context_kind IN ('selection', 'reflow_block')",
            name="ck_translation_results_context_kind",
        ),
        {"schema": "scholens"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    identity_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    context_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholens.documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_language: Mapped[str] = mapped_column(String(35), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    instructions_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
