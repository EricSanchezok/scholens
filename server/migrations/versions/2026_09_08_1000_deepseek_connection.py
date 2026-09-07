"""Allow user-owned DeepSeek credentials without changing existing connections."""

from alembic import op

revision = "2026_09_08_1000"
down_revision = "2026_09_05_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_integration_connections_provider",
        "integration_connections",
        schema="scholens",
        type_="check",
    )
    op.create_check_constraint(
        "ck_integration_connections_provider",
        "integration_connections",
        "provider IN ('deepseek', 'mineru', 'anysearch', 'tavily', 'exa', 'firecrawl', 'openalex', 'zotero')",
        schema="scholens",
    )


def downgrade() -> None:
    raise RuntimeError("Forward-only migration: preserve user connections")
