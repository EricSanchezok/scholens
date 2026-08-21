"""conversation search indexes (expand)

Revision ID: 35c4c441e6fc4fbb916917c50157929a
Revises: da5a5c29802d4ce38a49220a2b563ced
Create Date: 2026-08-21 16:30:00+08:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "35c4c441e6fc4fbb916917c50157929a"
down_revision: str | None = "da5a5c29802d4ce38a49220a2b563ced"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add independently usable lexical indexes without duplicating content."""
    op.execute(
        "CREATE INDEX ix_conversations_title_trgm "
        "ON scholens.conversations USING gin (lower(title) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_conversations_scope_label_trgm "
        "ON scholens.conversations USING gin "
        "(lower(coalesce(scope_label_snapshot, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_projects_title_trgm "
        "ON scholens.projects USING gin (lower(title) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_documents_title_trgm "
        "ON scholens.documents USING gin (lower(title) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_conversation_turns_user_query_trgm "
        "ON scholens.conversation_turns USING gin "
        "(lower(user_query) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_conversation_turns_user_query_fts "
        "ON scholens.conversation_turns USING gin "
        "(to_tsvector('pg_catalog.simple', user_query))"
    )
    op.execute(
        "CREATE INDEX ix_conversation_responses_content_trgm "
        "ON scholens.conversation_responses USING gin "
        "(lower(coalesce(content, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_conversation_responses_content_fts "
        "ON scholens.conversation_responses USING gin "
        "(to_tsvector('pg_catalog.simple', coalesce(content, '')))"
    )
