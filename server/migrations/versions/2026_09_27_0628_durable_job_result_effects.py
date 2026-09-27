"""durable job result effects

Revision ID: 2026_09_27_1200
Revises: 2026_09_27_1100
Create Date: 2026-09-27 06:28:40.033730+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2026_09_27_1200"
down_revision: Union[str, None] = "2026_09_27_1100"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "job_result_effects",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("claim_generation", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("claim_id", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'applying', 'applied')", name="ck_job_effect_status"
        ),
        sa.CheckConstraint(
            "(claim_id IS NULL) = (lease_expires_at IS NULL)",
            name="ck_job_effect_lease_pair",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["scholens.jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "claim_generation", "ordinal"),
        schema="scholens",
    )
    op.create_index(
        "ix_job_effect_pending",
        "job_result_effects",
        ["status", "available_at"],
        unique=False,
        schema="scholens",
    )


def downgrade() -> None:
    raise RuntimeError("Forward-only migration: preserve pending job effects")
