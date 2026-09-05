"""Add versioned multilingual embeddings to canonical document passages."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "2026_09_05_1400"
down_revision = "2026_08_26_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_passages",
        sa.Column("embedding", Vector(384), nullable=True),
        schema="scholens",
    )
    op.add_column(
        "document_passages",
        sa.Column("embedding_model_revision", sa.String(length=128), nullable=True),
        schema="scholens",
    )
    op.add_column(
        "document_passages",
        sa.Column("embedding_source_digest", sa.String(length=64), nullable=True),
        schema="scholens",
    )
    op.add_column(
        "document_passages",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        schema="scholens",
    )
    op.create_index(
        "ix_document_passages_embedding_revision",
        "document_passages",
        ["embedding_model_revision"],
        schema="scholens",
    )
    op.create_index(
        "ix_document_passages_embedding_hnsw_cosine",
        "document_passages",
        ["embedding"],
        schema="scholens",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_where=sa.text("embedding IS NOT NULL"),
    )


def downgrade() -> None:
    # Expand revisions are intentionally forward-only. Application rollback is
    # safe because every added field is nullable; destructive schema cleanup
    # belongs in a later contract revision after the compatibility window.
    raise RuntimeError("passage_embeddings_expand_revision_is_forward_only")
