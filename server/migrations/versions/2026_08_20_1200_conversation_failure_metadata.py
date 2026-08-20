"""persist safe conversation failure metadata (expand)

Revision ID: 4d8c9e5ab761
Revises: 8a8f20189e5c45c5aceb09eb45dd8e87
Create Date: 2026-08-20 12:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "4d8c9e5ab761"
down_revision: str | None = "8a8f20189e5c45c5aceb09eb45dd8e87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional safe failure metadata without changing existing rows."""
    op.add_column(
        "conversation_responses",
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="scholens",
    )
