"""Add an independent encrypted store for user-owned model connections."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "2026_09_08_1000"
down_revision = "2026_09_05_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_connections",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("credential_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "configuration", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("credential_revision", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "provider"),
        schema="scholens",
    )


def downgrade() -> None:
    raise RuntimeError("Forward-only migration: preserve user connections")
