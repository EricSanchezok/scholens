"""conversation search indexes (expand)

Revision ID: 35c4c441e6fc4fbb916917c50157929a
Revises: da5a5c29802d4ce38a49220a2b563ced
Create Date: 2026-08-21 16:30:00+08:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "35c4c441e6fc4fbb916917c50157929a"
down_revision: str | None = "da5a5c29802d4ce38a49220a2b563ced"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add independently usable lexical indexes without duplicating content."""
    op.create_index(
        "ix_conversations_title_trgm",
        "conversations",
        [sa.text("lower(title) gin_trgm_ops")],
        schema="scholens",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_conversations_scope_label_trgm",
        "conversations",
        [sa.text("lower(coalesce(scope_label_snapshot, '')) gin_trgm_ops")],
        schema="scholens",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_projects_title_trgm",
        "projects",
        [sa.text("lower(title) gin_trgm_ops")],
        schema="scholens",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_documents_title_trgm",
        "documents",
        [sa.text("lower(title) gin_trgm_ops")],
        schema="scholens",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_conversation_turns_user_query_trgm",
        "conversation_turns",
        [sa.text("lower(user_query) gin_trgm_ops")],
        schema="scholens",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_conversation_turns_user_query_fts",
        "conversation_turns",
        [sa.text("to_tsvector('simple'::regconfig, user_query)")],
        schema="scholens",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_conversation_responses_content_trgm",
        "conversation_responses",
        [sa.text("lower(coalesce(content, '')) gin_trgm_ops")],
        schema="scholens",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_conversation_responses_content_fts",
        "conversation_responses",
        [sa.text("to_tsvector('simple'::regconfig, COALESCE(content, ''::text))")],
        schema="scholens",
        postgresql_using="gin",
    )
