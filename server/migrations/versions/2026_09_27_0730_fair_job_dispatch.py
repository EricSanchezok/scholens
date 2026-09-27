"""Add durable requester rotation and bounded live-dispatch query indexes.

Revision ID: 2026_09_27_1400
Revises: 2026_09_27_1300
"""

from alembic import op
import sqlalchemy as sa

revision = "2026_09_27_1400"
down_revision = "2026_09_27_1300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_dispatch_cursors",
        sa.Column("queue", sa.String(80), primary_key=True),
        sa.Column(
            "last_requester_id", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="scholens",
    )
    op.create_index(
        "ix_jobs_live_dispatch",
        "jobs",
        ["id"],
        schema="scholens",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_index(
        "ix_job_dispatches_queue_status",
        "job_dispatches",
        ["queue", "status", "available_at"],
        schema="scholens",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Forward-only expansion; rollback application code without deleting durable cursors"
    )
