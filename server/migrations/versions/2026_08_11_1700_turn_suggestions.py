"""move follow-up suggestions to conversation turns

Revision ID: 2f6b39c8d102
Revises: 77a0c6af7e31
Create Date: 2026-08-11 17:00:00+08:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "2f6b39c8d102"
down_revision: str | None = "77a0c6af7e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_turns",
        sa.Column(
            "suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        schema="scholens",
    )
    op.drop_constraint(
        "ck_conversation_responses_suggestions_status",
        "conversation_responses",
        schema="scholens",
        type_="check",
    )
    op.drop_column("conversation_responses", "suggestions_status", schema="scholens")
    op.drop_column("conversation_responses", "suggestions", schema="scholens")


def downgrade() -> None:
    op.add_column(
        "conversation_responses",
        sa.Column(
            "suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        schema="scholens",
    )
    op.add_column(
        "conversation_responses",
        sa.Column(
            "suggestions_status",
            sa.String(length=16),
            server_default="idle",
            nullable=False,
        ),
        schema="scholens",
    )
    op.create_check_constraint(
        "ck_conversation_responses_suggestions_status",
        "conversation_responses",
        "suggestions_status IN ('idle', 'pending', 'completed', 'failed')",
        schema="scholens",
    )
    op.drop_column("conversation_turns", "suggestions", schema="scholens")
