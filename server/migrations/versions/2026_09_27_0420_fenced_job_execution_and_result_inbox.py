"""fenced job execution and result inbox

Revision ID: 2026_09_27_1000
Revises: 2026_09_08_1000
Create Date: 2026-09-27 04:20:12.784866+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2026_09_27_1000"
down_revision: Union[str, None] = "2026_09_08_1000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "job_executions",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column(
            "claim_generation", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("claim_token", sa.UUID(), nullable=True),
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
        sa.CheckConstraint("claim_generation >= 0", name="ck_job_execution_generation"),
        sa.ForeignKeyConstraint(["job_id"], ["scholens.jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
        schema="scholens",
    )
    op.create_table(
        "job_result_inbox",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("claim_generation", sa.BigInteger(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("delivery_ref", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("apply_claim_id", sa.UUID(), nullable=True),
        sa.Column("apply_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('pending', 'applying', 'applied', 'rejected')",
            name="ck_job_result_status",
        ),
        sa.CheckConstraint(
            "(apply_claim_id IS NULL) = (apply_lease_expires_at IS NULL)",
            name="ck_job_result_lease_pair",
        ),
        sa.CheckConstraint("claim_generation > 0", name="ck_job_result_generation"),
        sa.ForeignKeyConstraint(["job_id"], ["scholens.jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "claim_generation"),
        schema="scholens",
    )
    op.create_index(
        "ix_job_result_pending",
        "job_result_inbox",
        ["status", "available_at"],
        unique=False,
        schema="scholens",
    )


def downgrade() -> None:
    raise RuntimeError("Forward-only migration: preserve accepted job results")
