"""Allow source-first ingestion reservations without a known digest."""

from alembic import op
import sqlalchemy as sa


revision = "2026_08_26_1200"
down_revision = "a84f3d7c2b91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "upload_reservations",
        "content_sha256",
        existing_type=sa.String(length=64),
        nullable=True,
        schema="scholens",
    )


def downgrade() -> None:
    # The expand revision is intentionally forward-only. Contract tightening
    # belongs in a later migrate/switch/contract revision, never in the same
    # revision's downgrade path.
    bind = op.get_bind()
    remaining = bind.execute(
        sa.text(
            "SELECT 1 FROM scholens.upload_reservations "
            "WHERE content_sha256 IS NULL LIMIT 1"
        )
    ).first()
    if remaining is not None:
        raise RuntimeError("cannot_make_source_reservation_digest_non_nullable")
    raise RuntimeError("source_reservation_nullable_revision_is_forward_only")
