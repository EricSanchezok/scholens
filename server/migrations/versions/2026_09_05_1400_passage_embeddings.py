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
    op.drop_index(
        "ix_document_passages_embedding_hnsw_cosine",
        table_name="document_passages",
        schema="scholens",
    )
    op.drop_index(
        "ix_document_passages_embedding_revision",
        table_name="document_passages",
        schema="scholens",
    )
    op.drop_column("document_passages", "embedded_at", schema="scholens")
    op.drop_column("document_passages", "embedding_source_digest", schema="scholens")
    op.drop_column("document_passages", "embedding_model_revision", schema="scholens")
    op.drop_column("document_passages", "embedding", schema="scholens")
