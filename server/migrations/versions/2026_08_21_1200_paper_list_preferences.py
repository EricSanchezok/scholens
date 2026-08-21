"""paper list preferences

Revision ID: b927c848e16a
Revises: 35c4c441e6fc4fbb916917c50157929a
Create Date: 2026-08-21 12:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b927c848e16a"
down_revision: str | None = "35c4c441e6fc4fbb916917c50157929a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_list_preferences",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("visible_columns", postgresql.JSONB(), nullable=False),
        sa.Column(
            "preview_open",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id"),
        schema="scholens",
    )


def downgrade() -> None:
    op.drop_table("paper_list_preferences", schema="scholens")
