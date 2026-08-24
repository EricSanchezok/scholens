"""reading activity ledger and aggregate projections (expand)

Revision ID: e72b4a1c9d03
Revises: 6e5c2a3f1b9d
Create Date: 2026-08-24 17:00:00+08:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e72b4a1c9d03"
down_revision: str | None = "6e5c2a3f1b9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("page_count", sa.Integer(), nullable=True),
        schema="scholens",
    )

    op.create_table(
        "reading_metric_definitions",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column(
            "collection_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("version"),
        schema="scholens",
    )
    op.bulk_insert(
        sa.table(
            "reading_metric_definitions",
            sa.column("version", sa.String(length=64)),
            schema="scholens",
        ),
        [{"version": "active-reading-v1"}],
    )

    op.create_table(
        "reading_activity_preferences",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "recording_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "contribute_anonymous_project_aggregates",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        schema="scholens",
    )

    op.create_table(
        "reading_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("view_mode", sa.String(length=16), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("metric_definition_version", sa.String(length=64), nullable=False),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "visible_ms", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "active_ms", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_snapshot_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "contribute_to_project_aggregates",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("page_detail_purged_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "view_mode IN ('pdf', 'reflow')",
            name="ck_reading_sessions_view_mode",
        ),
        sa.CheckConstraint(
            "revision >= 0", name="ck_reading_sessions_revision_nonnegative"
        ),
        sa.CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_sessions_duration",
        ),
        sa.CheckConstraint(
            "last_seen_at >= started_at",
            name="ck_reading_sessions_last_seen_at",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= last_seen_at",
            name="ck_reading_sessions_ended_at",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["metric_definition_version"],
            ["scholens.reading_metric_definitions.version"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["scholens.documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["scholens.projects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "metric_definition_version",
            name="uq_reading_sessions_id_metric_version",
        ),
        schema="scholens",
    )
    op.create_index(
        "ix_reading_sessions_user_document_last_seen",
        "reading_sessions",
        ["user_id", "document_id", "last_seen_at"],
        schema="scholens",
    )
    op.create_index(
        "ix_reading_sessions_document_id",
        "reading_sessions",
        ["document_id"],
        schema="scholens",
    )
    op.create_index(
        "ix_reading_sessions_user_id",
        "reading_sessions",
        ["user_id", "id"],
        schema="scholens",
    )
    op.create_index(
        "ix_reading_sessions_project_user_last_seen",
        "reading_sessions",
        ["project_id", "user_id", "last_seen_at"],
        schema="scholens",
    )
    op.create_index(
        "ix_reading_sessions_page_detail_retention",
        "reading_sessions",
        ["started_at"],
        schema="scholens",
        postgresql_where=sa.text("page_detail_purged_at IS NULL"),
    )

    op.create_table(
        "reading_session_hours",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_definition_version", sa.String(length=64), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "visible_ms", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "active_ms", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "session_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_session_hours_duration",
        ),
        sa.CheckConstraint(
            "session_count IN (0, 1)",
            name="ck_reading_session_hours_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "metric_definition_version"],
            [
                "scholens.reading_sessions.id",
                "scholens.reading_sessions.metric_definition_version",
            ],
            ondelete="CASCADE",
            name="fk_reading_session_hours_session_version",
        ),
        sa.ForeignKeyConstraint(
            ["metric_definition_version"],
            ["scholens.reading_metric_definitions.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", "bucket_start"),
        schema="scholens",
    )
    op.create_index(
        "ix_reading_session_hours_bucket",
        "reading_session_hours",
        ["bucket_start"],
        schema="scholens",
    )

    op.create_table(
        "reading_session_pages",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_definition_version", sa.String(length=64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("visible_ms", sa.BigInteger(), nullable=False),
        sa.Column("active_ms", sa.BigInteger(), nullable=False),
        sa.Column("visit_count", sa.Integer(), nullable=False),
        sa.Column(
            "vertical_segments_ms",
            postgresql.ARRAY(sa.BigInteger()),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "page_number BETWEEN 1 AND 10000",
            name="ck_reading_session_pages_page_number",
        ),
        sa.CheckConstraint(
            "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
            name="ck_reading_session_pages_duration",
        ),
        sa.CheckConstraint(
            "visit_count >= 0", name="ck_reading_session_pages_visit_count"
        ),
        sa.CheckConstraint(
            "cardinality(vertical_segments_ms) = 20",
            name="ck_reading_session_pages_segments",
        ),
        sa.CheckConstraint(
            "0 <= ALL(vertical_segments_ms)",
            name="ck_reading_session_pages_segments_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "metric_definition_version"],
            [
                "scholens.reading_sessions.id",
                "scholens.reading_sessions.metric_definition_version",
            ],
            ondelete="CASCADE",
            name="fk_reading_session_pages_session_version",
        ),
        sa.ForeignKeyConstraint(
            ["metric_definition_version"],
            ["scholens.reading_metric_definitions.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", "page_number"),
        schema="scholens",
    )
    _create_page_rollup("reading_personal_page_rollups", project=False)
    _create_page_rollup("reading_project_page_rollups", project=True)
    _create_page_rollup("reading_project_personal_page_rollups", project=True)
    _create_hour_rollup("reading_personal_hour_rollups", project=False)
    _create_hour_rollup("reading_project_hour_rollups", project=True)


def _create_page_rollup(
    table: str,
    *,
    project: bool,
) -> None:
    columns: list[sa.Column[object]] = []
    constraints: list[object] = []
    primary: list[str] = []
    if project:
        columns.append(
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False)
        )
        constraints.append(
            sa.ForeignKeyConstraint(
                ["project_id"], ["scholens.projects.id"], ondelete="CASCADE"
            )
        )
        primary.append("project_id")
    columns.extend(
        [
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "metric_definition_version", sa.String(length=64), nullable=False
            ),
            sa.Column("page_number", sa.Integer(), nullable=False),
        ]
    )
    if project:
        columns.append(sa.Column("active_ms", sa.BigInteger(), nullable=False))
    else:
        columns.extend(
            [
                sa.Column("visible_ms", sa.BigInteger(), nullable=False),
                sa.Column("active_ms", sa.BigInteger(), nullable=False),
                sa.Column("visit_count", sa.BigInteger(), nullable=False),
                sa.Column(
                    "vertical_segments_ms",
                    postgresql.ARRAY(sa.BigInteger()),
                    nullable=False,
                ),
            ]
        )
    columns.extend(_timestamps())
    primary.extend(
        ["user_id", "document_id", "metric_definition_version", "page_number"]
    )
    constraints.extend(
        [
            sa.CheckConstraint(
                "page_number BETWEEN 1 AND 10000",
                name=f"ck_{table}_page_number",
            ),
            sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["document_id"], ["scholens.documents.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["metric_definition_version"],
                ["scholens.reading_metric_definitions.version"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint(*primary),
        ]
    )
    if project:
        constraints.append(
            sa.CheckConstraint("active_ms >= 0", name=f"ck_{table}_active_ms")
        )
    else:
        constraints.extend(
            [
                sa.CheckConstraint(
                    "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
                    name=f"ck_{table}_duration",
                ),
                sa.CheckConstraint(
                    "visit_count >= 0",
                    name=f"ck_{table}_visit_count",
                ),
                sa.CheckConstraint(
                    "cardinality(vertical_segments_ms) = 20",
                    name=f"ck_{table}_segments",
                ),
                sa.CheckConstraint(
                    "0 <= ALL(vertical_segments_ms)",
                    name=f"ck_{table}_segments_nonnegative",
                ),
            ]
        )
    op.create_table(table, *columns, *constraints, schema="scholens")
    op.create_index(
        f"ix_{table}_document_id",
        table,
        ["document_id"],
        schema="scholens",
    )
    if project:
        op.create_index(
            f"ix_{table}_user_export",
            table,
            [
                "user_id",
                "project_id",
                "document_id",
                "metric_definition_version",
                "page_number",
            ],
            schema="scholens",
        )


def _create_hour_rollup(table: str, *, project: bool) -> None:
    columns: list[sa.Column[object]] = []
    constraints: list[object] = []
    primary: list[str] = []
    if project:
        columns.append(
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False)
        )
        constraints.append(
            sa.ForeignKeyConstraint(
                ["project_id"], ["scholens.projects.id"], ondelete="CASCADE"
            )
        )
        primary.append("project_id")
    columns.extend(
        [
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "metric_definition_version", sa.String(length=64), nullable=False
            ),
            sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("visible_ms", sa.BigInteger(), nullable=False),
            sa.Column("active_ms", sa.BigInteger(), nullable=False),
            *_timestamps(),
        ]
    )
    if not project:
        columns.insert(
            -2,
            sa.Column("session_count", sa.BigInteger(), nullable=False),
        )
    primary.extend(
        ["user_id", "document_id", "metric_definition_version", "bucket_start"]
    )
    constraints.extend(
        [
            sa.CheckConstraint(
                "visible_ms >= 0 AND active_ms >= 0 AND active_ms <= visible_ms",
                name=f"ck_{table}_duration",
            ),
            sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["document_id"], ["scholens.documents.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["metric_definition_version"],
                ["scholens.reading_metric_definitions.version"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint(*primary),
        ]
    )
    if not project:
        constraints.append(
            sa.CheckConstraint("session_count >= 0", name=f"ck_{table}_sessions")
        )
    op.create_table(table, *columns, *constraints, schema="scholens")
    op.create_index(
        f"ix_{table}_document_id",
        table,
        ["document_id"],
        schema="scholens",
    )
    prefix = "reading_project" if project else "reading_personal"
    op.create_index(
        f"ix_{prefix}_hours_{'project_bucket' if project else 'user_bucket'}",
        table,
        ["project_id", "bucket_start"] if project else ["user_id", "bucket_start"],
        schema="scholens",
    )
    if project:
        op.create_index(
            "ix_reading_project_hours_user_export",
            table,
            [
                "user_id",
                "project_id",
                "document_id",
                "metric_definition_version",
                "bucket_start",
            ],
            schema="scholens",
        )


def downgrade() -> None:
    # Production schema evolution is forward-only. Older applications safely
    # ignore these additive tables and the nullable Document column.
    pass
