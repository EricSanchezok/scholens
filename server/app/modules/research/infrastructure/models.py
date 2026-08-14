"""Shared metadata and strongly typed research outputs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    UUID,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.domain import JsonValue
from app.shared.infrastructure.persistence import Base
from app.shared.domain.enums import (
    AnnotationThreadStatus,
    ResearchItemKind,
    ResearchAudienceType,
)

if TYPE_CHECKING:
    from app.modules.conversations.infrastructure.models import ConversationResponse
    from app.modules.papers.infrastructure.models import Document
    from app.modules.identity.infrastructure.models import AuthUser
    from app.modules.jobs.infrastructure.models import DurableJob
    from app.modules.projects.infrastructure.models import Project


class ResearchItem(Base):
    __tablename__ = "research_items"
    __table_args__ = (
        CheckConstraint(
            "color IN ('yellow', 'red', 'green', 'blue', 'purple', "
            "'magenta', 'orange', 'gray')",
            name="ck_annotation_threads_color",
        ),
        CheckConstraint(
            "(audience_type = 'personal' AND audience_document_id IS NULL "
            "AND audience_project_id IS NULL) "
            "OR (audience_type = 'document' AND audience_document_id IS NOT NULL "
            "AND audience_project_id IS NULL) "
            "OR (audience_type = 'project' AND audience_project_id IS NOT NULL "
            "AND audience_document_id IS NULL)",
            name="ck_research_items_audience_consistency",
        ),
        CheckConstraint(
            "kind != 'annotation_thread' OR "
            "(target_document_id IS NOT NULL AND audience_type IN ('personal', 'project'))",
            name="ck_research_items_annotation_audience",
        ),
        Index(
            "ix_research_items_document_audience",
            "audience_document_id",
            "created_at",
        ),
        Index(
            "ix_research_items_project_audience",
            "audience_project_id",
            "created_at",
        ),
        Index(
            "ix_research_items_annotation_target", "target_document_id", "created_at"
        ),
        Index(
            "ix_research_items_creator_activity",
            "created_by_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    audience_type: Mapped[str] = mapped_column(String(16), nullable=False)
    audience_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    audience_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    target_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_response_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_responses.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )

    created_by: Mapped["AuthUser | None"] = relationship(
        "AuthUser",
        foreign_keys=[created_by_id],
        back_populates="research_items",
    )
    audience_document: Mapped["Document | None"] = relationship(
        "Document", foreign_keys=[audience_document_id]
    )
    audience_project: Mapped["Project | None"] = relationship(
        "Project", foreign_keys=[audience_project_id]
    )
    target_document: Mapped["Document | None"] = relationship(
        "Document", foreign_keys=[target_document_id]
    )
    source_response: Mapped["ConversationResponse | None"] = relationship(
        "ConversationResponse",
        back_populates="research_items",
    )
    source_job: Mapped["DurableJob | None"] = relationship("DurableJob")
    annotation_thread: Mapped["AnnotationThread | None"] = relationship(
        "AnnotationThread",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    citation: Mapped["CitationOutput | None"] = relationship(
        "CitationOutput",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    audio_overview: Mapped["ResearchAudioOverview | None"] = relationship(
        "ResearchAudioOverview",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    data_table: Mapped["ResearchDataTable | None"] = relationship(
        "ResearchDataTable",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )


class AnnotationThread(Base):
    __tablename__ = "annotation_threads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_annotation_threads_status",
        ),
        CheckConstraint(
            "(status = 'open' AND resolved_by_id IS NULL AND resolved_at IS NULL) "
            "OR (status = 'resolved' AND resolved_at IS NOT NULL)",
            name="ck_annotation_threads_resolution",
        ),
    )

    research_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    color: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="yellow",
        server_default="yellow",
    )
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="user",
        server_default="user",
    )
    zotero_annotation_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AnnotationThreadStatus.OPEN.value,
        server_default=AnnotationThreadStatus.OPEN.value,
    )
    resolved_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    item: Mapped["ResearchItem"] = relationship(
        "ResearchItem",
        back_populates="annotation_thread",
    )
    comments: Mapped[list["AnnotationComment"]] = relationship(
        "AnnotationComment",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="AnnotationComment.created_at",
    )
    resolved_by: Mapped["AuthUser | None"] = relationship(
        "AuthUser", foreign_keys=[resolved_by_id]
    )


class AnnotationComment(Base):
    __tablename__ = "annotation_comments"
    __table_args__ = (
        Index("ix_annotation_comments_thread", "thread_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("annotation_threads.research_item_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="user",
        server_default="user",
    )

    thread: Mapped["AnnotationThread"] = relationship(
        "AnnotationThread",
        back_populates="comments",
    )
    created_by: Mapped["AuthUser | None"] = relationship(
        "AuthUser",
        foreign_keys=[created_by_id],
        back_populates="annotation_comments",
    )


class CitationOutput(Base):
    __tablename__ = "citation_outputs"

    research_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    snapshot: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, nullable=False)

    item: Mapped["ResearchItem"] = relationship(
        "ResearchItem",
        back_populates="citation",
    )


class ResearchAudioOverview(Base):
    __tablename__ = "research_audio_overviews"

    research_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    s3_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    voice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str] = mapped_column(String(160), nullable=False)

    item: Mapped["ResearchItem"] = relationship(
        "ResearchItem",
        back_populates="audio_overview",
    )


class ResearchDataTable(Base):
    __tablename__ = "research_data_tables"

    research_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    columns: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    rows: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    citations: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    row_failures: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    item: Mapped["ResearchItem"] = relationship(
        "ResearchItem",
        back_populates="data_table",
    )


__all__ = [
    "AnnotationComment",
    "CitationOutput",
    "AnnotationThread",
    "ResearchAudioOverview",
    "ResearchDataTable",
    "ResearchItem",
    "ResearchItemKind",
    "ResearchAudienceType",
]
