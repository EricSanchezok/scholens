"""failed paper ingestion dismissal (expand)

Revision ID: a84f3d7c2b91
Revises: e72b4a1c9d03
Create Date: 2026-08-25 11:00:00+08:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a84f3d7c2b91"
down_revision: str | None = "e72b4a1c9d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "upload_reservations",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        schema="scholens",
    )


def downgrade() -> None:
    # Production schema evolution is forward-only. Older revisions ignore this
    # additive visibility field and continue to show the failed ingestion.
    pass
