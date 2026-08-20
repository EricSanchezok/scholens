"""align search embedding timestamps with the persistence model (expand)

Revision ID: da5a5c29802d4ce38a49220a2b563ced
Revises: f15a6d4273c14bd4ad7ec7780cf765e0
Create Date: 2026-08-20 12:30:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "da5a5c29802d4ce38a49220a2b563ced"
down_revision: str | None = "f15a6d4273c14bd4ad7ec7780cf765e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the timestamp columns inherited from the canonical persistence base."""
    op.add_column(
        "document_search_embeddings",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="scholens",
    )
    op.add_column(
        "document_search_embeddings",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="scholens",
    )
