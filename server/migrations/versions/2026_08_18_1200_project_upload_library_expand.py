"""project uploads default to the personal library (expand)

Revision ID: 8a8f20189e5c45c5aceb09eb45dd8e87
Revises: c9f4a62d01ab
Create Date: 2026-08-18 12:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "8a8f20189e5c45c5aceb09eb45dd8e87"
down_revision: str | None = "c9f4a62d01ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the additive columns required by the add_to_library ingestion semantics.

    This revision is purely additive: no drop, FK, or data reinterpretation,
    so it stays compatible with the pre-change application.
    """
    op.add_column(
        "upload_reservations",
        sa.Column(
            "add_to_library",
            sa.Boolean(),
            nullable=True,
        ),
        schema="scholens",
    )
    op.add_column(
        "upload_reservations",
        sa.Column(
            "reference_created_library",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="scholens",
    )
    op.add_column(
        "upload_reservations",
        sa.Column(
            "reference_created_project",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="scholens",
    )
    op.add_column(
        "upload_reservations",
        sa.Column("library_quota_owner_id", sa.BigInteger(), nullable=True),
        schema="scholens",
    )
    op.add_column(
        "upload_reservations",
        sa.Column(
            "library_reserved_reference_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema="scholens",
    )
    op.add_column(
        "upload_reservations",
        sa.Column(
            "library_reserved_size_kb",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema="scholens",
    )
    op.create_index(
        "ix_upload_reservations_library_quota_owner",
        "upload_reservations",
        ["library_quota_owner_id"],
        unique=False,
        schema="scholens",
    )
    op.add_column(
        "paper_upload_sessions",
        sa.Column(
            "add_to_library",
            sa.Boolean(),
            nullable=True,
        ),
        schema="scholens",
    )
