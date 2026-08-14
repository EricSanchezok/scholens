from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from app.shared.infrastructure.persistence import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

if TYPE_CHECKING:
    from app.modules.jobs.infrastructure.models import DurableJob


class DocumentReflow(Base):
    __tablename__ = "document_reflows"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_document_reflows_status",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    job: Mapped["DurableJob"] = relationship(foreign_keys=[job_id])
    blocks: Mapped[list["DocumentReflowBlock"]] = relationship(
        back_populates="reflow",
        cascade="all, delete-orphan",
        order_by="DocumentReflowBlock.block_index",
    )


class DocumentReflowBlock(Base):
    __tablename__ = "document_reflow_blocks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "block_index",
            name="uq_document_reflow_blocks_document_index",
        ),
        CheckConstraint("block_index >= 0", name="ck_reflow_blocks_index"),
        CheckConstraint(
            "kind IN ('title', 'authors', 'heading', 'paragraph', 'list', "
            "'quote', 'equation', 'table', 'figure', 'code', 'references')",
            name="ck_reflow_blocks_kind",
        ),
        CheckConstraint(
            "heading_level IS NULL OR heading_level BETWEEN 1 AND 6",
            name="ck_reflow_blocks_heading_level",
        ),
        Index("ix_document_reflow_blocks_document", "document_id", "block_index"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_reflows.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reflow: Mapped[DocumentReflow] = relationship(back_populates="blocks")
