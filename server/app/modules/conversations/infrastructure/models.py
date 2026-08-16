from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    UUID,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.conversations.domain import DEFAULT_CONVERSATION_TITLE
from app.shared.domain import JsonValue
from app.shared.domain.enums import ConversationScopeType
from app.shared.infrastructure.persistence import Base

if TYPE_CHECKING:
    from app.modules.papers.infrastructure.models import Document
    from app.modules.identity.infrastructure.models import AuthUser
    from app.modules.projects.infrastructure.models import Project
    from app.modules.research.infrastructure.models import ResearchItem


class ConversationContextProject(Base):
    __tablename__ = "conversation_context_projects"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )


class ConversationContextDocument(Base):
    __tablename__ = "conversation_context_documents"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "parent_turn_id",
            "branch_index",
            name="uq_conversation_turns_sibling_branch",
        ),
        Index(
            "uq_conversation_turns_root_branch",
            "conversation_id",
            "branch_index",
            unique=True,
            postgresql_where=text("parent_turn_id IS NULL"),
        ),
        CheckConstraint("depth >= 1", name="ck_conversation_turns_depth"),
        CheckConstraint(
            "branch_index >= 1",
            name="ck_conversation_turns_branch_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    selected_child_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "conversation_turns.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_conversation_turns_selected_child_turn_id",
        ),
        nullable=True,
    )
    created_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    contexts: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    paper_context: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, nullable=False)
    reasoning_level: Mapped[str] = mapped_column(String(16), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(100), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_response_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "conversation_responses.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_conversation_turns_selected_response_id",
        ),
        nullable=True,
    )
    suggestions: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="turns",
        foreign_keys=[conversation_id],
    )
    responses: Mapped[list["ConversationResponse"]] = relationship(
        "ConversationResponse",
        back_populates="turn",
        order_by="ConversationResponse.variant_index",
        cascade="all, delete-orphan",
        foreign_keys="ConversationResponse.turn_id",
    )
    selected_response: Mapped["ConversationResponse | None"] = relationship(
        "ConversationResponse",
        primaryjoin="ConversationTurn.selected_response_id == ConversationResponse.id",
        foreign_keys=[selected_response_id],
        post_update=True,
    )


class ConversationResponse(Base):
    __tablename__ = "conversation_responses"
    __table_args__ = (
        UniqueConstraint(
            "turn_id",
            "variant_index",
            name="uq_conversation_responses_turn_variant",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_conversation_responses_status",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_conversation_responses_duration_ms",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    variant_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    references: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB, nullable=True
    )
    trace: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turn: Mapped["ConversationTurn"] = relationship(
        "ConversationTurn",
        back_populates="responses",
        foreign_keys=[turn_id],
    )
    research_items: Mapped[list["ResearchItem"]] = relationship(
        "ResearchItem",
        back_populates="source_response",
        order_by="ResearchItem.created_at",
        passive_deletes=True,
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "path_revision >= 0",
            name="ck_conversations_path_revision",
        ),
        CheckConstraint(
            "(scope_type = 'global' AND project_id IS NULL "
            "AND document_id IS NULL AND context_deleted_at IS NULL) OR "
            "(scope_type = 'project' AND document_id IS NULL AND "
            "((project_id IS NOT NULL AND context_deleted_at IS NULL) OR "
            "(project_id IS NULL AND context_deleted_at IS NOT NULL))) OR "
            "(scope_type = 'paper' AND project_id IS NULL AND "
            "((document_id IS NOT NULL AND context_deleted_at IS NULL) OR "
            "(document_id IS NULL AND context_deleted_at IS NOT NULL)))",
            name="ck_conversations_scope_consistency",
        ),
        CheckConstraint(
            "paper_context_kind IN ('library', 'selection')",
            name="ck_conversations_paper_context_kind",
        ),
        CheckConstraint(
            "tool_permissions IN ("
            "ARRAY[]::text[], "
            "ARRAY['read']::text[], "
            "ARRAY['write']::text[], "
            "ARRAY['manage']::text[], "
            "ARRAY['delete']::text[], "
            "ARRAY['read','write']::text[], "
            "ARRAY['read','manage']::text[], "
            "ARRAY['read','delete']::text[], "
            "ARRAY['write','manage']::text[], "
            "ARRAY['write','delete']::text[], "
            "ARRAY['manage','delete']::text[], "
            "ARRAY['read','write','manage']::text[], "
            "ARRAY['read','write','delete']::text[], "
            "ARRAY['read','manage','delete']::text[], "
            "ARRAY['write','manage','delete']::text[], "
            "ARRAY['read','write','manage','delete']::text[]"
            ")",
            name="ck_conversations_tool_permissions",
        ),
        Index(
            "ix_conversations_user_archive_activity",
            "user_id",
            "archived_at",
            "updated_at",
        ),
        Index("ix_conversations_user_pinned", "user_id", "pinned_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    selected_root_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "conversation_turns.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_conversations_selected_root_turn_id",
        ),
        nullable=True,
    )
    path_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    title: Mapped[str] = mapped_column(
        String(240), nullable=False, default=DEFAULT_CONVERSATION_TITLE
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ConversationScopeType.PAPER,
    )
    paper_context_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="selection", server_default="selection"
    )
    tool_permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=lambda: ["read", "write"],
        server_default="{read,write}",
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scope_label_snapshot: Mapped[str | None] = mapped_column(String(240), nullable=True)
    context_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paper: Mapped["Document | None"] = relationship(
        "Document",
        foreign_keys=[document_id],
        back_populates="conversations",
    )
    project: Mapped["Project | None"] = relationship(
        "Project",
        foreign_keys=[project_id],
        back_populates="conversations",
    )
    user: Mapped["AuthUser | None"] = relationship(
        "AuthUser", back_populates="conversations"
    )
    turns: Mapped[list["ConversationTurn"]] = relationship(
        "ConversationTurn",
        back_populates="conversation",
        order_by=(ConversationTurn.depth, ConversationTurn.branch_index),
        cascade="all, delete-orphan",
        foreign_keys=[ConversationTurn.conversation_id],
    )
    context_projects: Mapped[list["ConversationContextProject"]] = relationship(
        "ConversationContextProject", cascade="all, delete-orphan"
    )
    context_documents: Mapped[list["ConversationContextDocument"]] = relationship(
        "ConversationContextDocument", cascade="all, delete-orphan"
    )
