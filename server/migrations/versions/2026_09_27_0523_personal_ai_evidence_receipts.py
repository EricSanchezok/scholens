"""personal AI evidence receipts

Revision ID: 2026_09_27_1100
Revises: 2026_09_27_1000
Create Date: 2026-09-27 05:23:19.765178+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2026_09_27_1100"
down_revision: Union[str, None] = "2026_09_27_1000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_annotation_evidence",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("evidence_digest", sa.String(length=64), nullable=False),
        sa.Column("research_item_id", sa.UUID(), nullable=True),
        sa.Column("source_job_id", sa.UUID(), nullable=True),
        sa.Column("execution_generation", sa.BigInteger(), nullable=True),
        sa.Column("segment_id", sa.String(length=160), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
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
            "execution_generation IS NULL OR execution_generation > 0",
            name="ck_ai_evidence_generation",
        ),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_ai_evidence_offsets",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["scholens.documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["research_item_id"], ["scholens.research_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_job_id"], ["scholens.jobs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "user_id", "document_id", "content_digest", "evidence_digest"
        ),
        schema="scholens",
    )
    op.create_index(
        "ix_ai_evidence_research_item",
        "ai_annotation_evidence",
        ["research_item_id"],
        unique=False,
        schema="scholens",
    )
    op.create_index(
        "ix_ai_evidence_source_job",
        "ai_annotation_evidence",
        ["source_job_id"],
        unique=False,
        schema="scholens",
    )


def downgrade() -> None:
    raise RuntimeError("Forward-only migration: preserve personal evidence receipts")
