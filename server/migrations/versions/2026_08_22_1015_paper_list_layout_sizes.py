"""paper list layout sizes (expand)

Revision ID: 6e5c2a3f1b9d
Revises: b927c848e16a
Create Date: 2026-08-22 10:15:00+08:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "6e5c2a3f1b9d"
down_revision: str | None = "b927c848e16a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper_list_preferences",
        sa.Column(
            "column_widths",
            postgresql.JSONB(),
            server_default=sa.text(
                '\'{"paper": 360, "status": 96, "tags": 160, '
                '"authors": 176, "publication": 144, '
                '"last_opened": 120, "added_at": 120, "doi": 160}\'::jsonb'
            ),
            nullable=False,
        ),
        schema="scholens",
    )
    op.add_column(
        "paper_list_preferences",
        sa.Column(
            "preview_width",
            sa.Integer(),
            server_default=sa.text("512"),
            nullable=False,
        ),
        schema="scholens",
    )


def downgrade() -> None:
    # Production schema evolution is forward-only. Application rollback keeps
    # these additive preference fields in place and older revisions ignore them.
    pass
