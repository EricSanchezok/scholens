"""SQLAlchemy persistence for durable reading activity and its projections."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    func,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.reading_activity.domain import PAGE_VERTICAL_SEGMENT_COUNT
from app.shared.infrastructure.persistence import Base


class ReadingMetricDefinition(Base):
    __tablename__ = "reading_metric_definitions"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReadingActivityPreference(Base):
    __tablename__ = "reading_activity_preferences"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    recording_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    contribute_anonymous_project_aggregates: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )


class ReadingSession(Base):
    __tablename__ = "reading_sessions"
    __table_args__ = (
        CheckConstraint(
            "view_mode IN ('pdf', 'reflow')",
            name="ck_reading_sessions_view_mode",
        ),
        CheckConstraint(
            "revision >= 0",
            name="ck_reading_sessions_revision_nonnegative",
        ),
        CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_sessions_duration",
        ),
        CheckConstraint(
            "last_seen_at >= started_at",
            name="ck_reading_sessions_last_seen_at",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= last_seen_at",
            name="ck_reading_sessions_ended_at",
        ),
        UniqueConstraint(
            "id",
            "metric_definition_version",
            name="uq_reading_sessions_id_metric_version",
        ),
        Index(
            "ix_reading_sessions_user_document_last_seen",
            "user_id",
            "document_id",
            "last_seen_at",
        ),
        Index("ix_reading_sessions_document_id", "document_id"),
        Index("ix_reading_sessions_user_id", "user_id", "id"),
        Index(
            "ix_reading_sessions_project_user_last_seen",
            "project_id",
            "user_id",
            "last_seen_at",
        ),
        Index(
            "ix_reading_sessions_page_detail_retention",
            "started_at",
            postgresql_where=text("page_detail_purged_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    view_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_definition_version: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reading_metric_definitions.version", ondelete="RESTRICT"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    visible_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    active_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_snapshot_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contribute_to_project_aggregates: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    page_detail_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ReadingSessionHour(Base):
    """Per-session coarse source rows kept for exact rollup repair/deletion."""

    __tablename__ = "reading_session_hours"
    __table_args__ = (
        CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_session_hours_duration",
        ),
        CheckConstraint(
            "session_count IN (0, 1)",
            name="ck_reading_session_hours_sessions",
        ),
        ForeignKeyConstraint(
            ["session_id", "metric_definition_version"],
            ["reading_sessions.id", "reading_sessions.metric_definition_version"],
            ondelete="CASCADE",
            name="fk_reading_session_hours_session_version",
        ),
        Index("ix_reading_session_hours_bucket", "bucket_start"),
    )

    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    metric_definition_version: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reading_metric_definitions.version", ondelete="RESTRICT"),
        nullable=False,
    )
    bucket_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    visible_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    active_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class ReadingSessionPage(Base):
    __tablename__ = "reading_session_pages"
    __table_args__ = (
        CheckConstraint(
            "page_number BETWEEN 1 AND 10000",
            name="ck_reading_session_pages_page_number",
        ),
        CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_session_pages_duration",
        ),
        CheckConstraint(
            "visit_count >= 0",
            name="ck_reading_session_pages_visit_count",
        ),
        CheckConstraint(
            f"cardinality(vertical_segments_ms) = {PAGE_VERTICAL_SEGMENT_COUNT}",
            name="ck_reading_session_pages_segments",
        ),
        CheckConstraint(
            "0 <= ALL(vertical_segments_ms)",
            name="ck_reading_session_pages_segments_nonnegative",
        ),
        ForeignKeyConstraint(
            ["session_id", "metric_definition_version"],
            ["reading_sessions.id", "reading_sessions.metric_definition_version"],
            ondelete="CASCADE",
            name="fk_reading_session_pages_session_version",
        ),
    )

    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    metric_definition_version: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reading_metric_definitions.version", ondelete="RESTRICT"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    visible_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vertical_segments_ms: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False
    )


class ReadingPersonalPageRollup(Base):
    __tablename__ = "reading_personal_page_rollups"
    __table_args__ = (
        CheckConstraint(
            "page_number BETWEEN 1 AND 10000",
            name="ck_reading_personal_page_rollups_page_number",
        ),
        CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_personal_page_rollups_duration",
        ),
        CheckConstraint(
            "visit_count >= 0",
            name="ck_reading_personal_page_rollups_visit_count",
        ),
        CheckConstraint(
            f"cardinality(vertical_segments_ms) = {PAGE_VERTICAL_SEGMENT_COUNT}",
            name="ck_reading_personal_page_rollups_segments",
        ),
        CheckConstraint(
            "0 <= ALL(vertical_segments_ms)",
            name="ck_reading_personal_page_rollups_segments_nonnegative",
        ),
        Index("ix_reading_personal_page_rollups_document_id", "document_id"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric_definition_version: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reading_metric_definitions.version", ondelete="RESTRICT"),
        primary_key=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    visible_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    visit_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vertical_segments_ms: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False
    )


class ReadingProjectPageRollup(Base):
    __tablename__ = "reading_project_page_rollups"
    __table_args__ = (
        CheckConstraint(
            "page_number BETWEEN 1 AND 10000",
            name="ck_reading_project_page_rollups_page_number",
        ),
        CheckConstraint(
            "active_ms >= 0",
            name="ck_reading_project_page_rollups_active_ms",
        ),
        Index(
            "ix_reading_project_page_rollups_user_export",
            "user_id",
            "project_id",
            "document_id",
            "metric_definition_version",
            "page_number",
        ),
        Index("ix_reading_project_page_rollups_document_id", "document_id"),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric_definition_version: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reading_metric_definitions.version", ondelete="RESTRICT"),
        primary_key=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ReadingProjectPersonalPageRollup(Base):
    """Actor-private lifetime page projection for one project attribution."""

    __tablename__ = "reading_project_personal_page_rollups"
    __table_args__ = (
        CheckConstraint(
            "page_number BETWEEN 1 AND 10000",
            name="ck_reading_project_personal_page_rollups_page_number",
        ),
        CheckConstraint(
            "active_ms >= 0",
            name="ck_reading_project_personal_page_rollups_active_ms",
        ),
        Index(
            "ix_reading_project_personal_page_rollups_user_export",
            "user_id",
            "project_id",
            "document_id",
            "metric_definition_version",
            "page_number",
        ),
        Index(
            "ix_reading_project_personal_page_rollups_document_id",
            "document_id",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric_definition_version: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reading_metric_definitions.version", ondelete="RESTRICT"),
        primary_key=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ReadingPersonalHourRollup(Base):
    __tablename__ = "reading_personal_hour_rollups"
    __table_args__ = (
        CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_personal_hour_rollups_duration",
        ),
        CheckConstraint(
            "session_count >= 0",
            name="ck_reading_personal_hour_rollups_sessions",
        ),
        Index(
            "ix_reading_personal_hours_user_bucket",
            "user_id",
            "bucket_start",
        ),
        Index("ix_reading_personal_hour_rollups_document_id", "document_id"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric_definition_version: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reading_metric_definitions.version", ondelete="RESTRICT"),
        primary_key=True,
    )
    bucket_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    visible_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_count: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ReadingProjectHourRollup(Base):
    __tablename__ = "reading_project_hour_rollups"
    __table_args__ = (
        CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_project_hour_rollups_duration",
        ),
        Index(
            "ix_reading_project_hours_project_bucket",
            "project_id",
            "bucket_start",
        ),
        Index(
            "ix_reading_project_hours_user_export",
            "user_id",
            "project_id",
            "document_id",
            "metric_definition_version",
            "bucket_start",
        ),
        Index("ix_reading_project_hour_rollups_document_id", "document_id"),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric_definition_version: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reading_metric_definitions.version", ondelete="RESTRICT"),
        primary_key=True,
    )
    bucket_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    visible_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


__all__ = [
    "ReadingActivityPreference",
    "ReadingMetricDefinition",
    "ReadingPersonalHourRollup",
    "ReadingPersonalPageRollup",
    "ReadingProjectHourRollup",
    "ReadingProjectPageRollup",
    "ReadingProjectPersonalPageRollup",
    "ReadingSession",
    "ReadingSessionHour",
    "ReadingSessionPage",
]
