"""add product entitlement grants and CLI operation provenance

Revision ID: c9f4a62d01ab
Revises: b12d7d620e91
Create Date: 2026-08-16 12:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c9f4a62d01ab"
down_revision: str | None = "b12d7d620e91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_plan_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("granted_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint("plan = 'researcher'", name="ck_account_plan_grants_plan"),
        sa.CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 500",
            name="ck_account_plan_grants_reason",
        ),
        sa.CheckConstraint(
            "revocation_reason IS NULL OR "
            "length(btrim(revocation_reason)) BETWEEN 1 AND 500",
            name="ck_account_plan_grants_revocation_reason",
        ),
        sa.CheckConstraint(
            "expires_at > created_at AND "
            "expires_at <= created_at + interval '365 days'",
            name="ck_account_plan_grants_duration",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL "
            "AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_account_plan_grants_revocation_state",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["auth.users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["auth.users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="scholens",
    )
    op.create_index(
        "ix_scholens_account_plan_grants_user_id",
        "account_plan_grants",
        ["user_id"],
        unique=False,
        schema="scholens",
    )
    op.create_index(
        "uq_account_plan_grants_unrevoked_user",
        "account_plan_grants",
        ["user_id"],
        unique=True,
        schema="scholens",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "account_quota_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("resource_key", sa.String(length=64), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("set_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=500), nullable=True),
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
            "resource_key IN ('paper_uploads', 'knowledge_base_size_kb', "
            "'token_credits_weekly', 'projects', 'project_papers')",
            name="ck_account_quota_overrides_resource",
        ),
        sa.CheckConstraint(
            "limit_value >= 0",
            name="ck_account_quota_overrides_value",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 500",
            name="ck_account_quota_overrides_reason",
        ),
        sa.CheckConstraint(
            "revocation_reason IS NULL OR "
            "length(btrim(revocation_reason)) BETWEEN 1 AND 500",
            name="ck_account_quota_overrides_revocation_reason",
        ),
        sa.CheckConstraint(
            "expires_at > created_at AND "
            "expires_at <= created_at + interval '365 days'",
            name="ck_account_quota_overrides_duration",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL "
            "AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_account_quota_overrides_revocation_state",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["auth.users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["set_by_user_id"],
            ["auth.users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="scholens",
    )
    op.create_index(
        "ix_scholens_account_quota_overrides_user_id",
        "account_quota_overrides",
        ["user_id"],
        unique=False,
        schema="scholens",
    )
    op.create_index(
        "uq_account_quota_overrides_unrevoked_resource",
        "account_quota_overrides",
        ["user_id", "resource_key"],
        unique=True,
        schema="scholens",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.drop_constraint(
        "ck_operation_journal_origin",
        "operation_journal_entries",
        schema="scholens",
        type_="check",
    )
    op.create_check_constraint(
        "ck_operation_journal_origin",
        "operation_journal_entries",
        "origin_kind IN ('http', 'conversation', 'mcp', 'job', 'webhook', "
        "'oauth_callback', 'scheduler', 'cli')",
        schema="scholens",
    )


def downgrade() -> None:
    # Intentionally retain ``cli`` in the origin vocabulary. Operation Journal
    # rows are append-only, so contracting this check after any CLI invocation
    # would either make downgrade fail or require rewriting audit history. This
    # is a one-way vocabulary extension even when the entitlement tables are
    # downgraded.
    op.drop_index(
        "uq_account_quota_overrides_unrevoked_resource",
        table_name="account_quota_overrides",
        schema="scholens",
    )
    op.drop_index(
        "ix_scholens_account_quota_overrides_user_id",
        table_name="account_quota_overrides",
        schema="scholens",
    )
    op.drop_table("account_quota_overrides", schema="scholens")
    op.drop_index(
        "uq_account_plan_grants_unrevoked_user",
        table_name="account_plan_grants",
        schema="scholens",
    )
    op.drop_index(
        "ix_scholens_account_plan_grants_user_id",
        table_name="account_plan_grants",
        schema="scholens",
    )
    op.drop_table("account_plan_grants", schema="scholens")
