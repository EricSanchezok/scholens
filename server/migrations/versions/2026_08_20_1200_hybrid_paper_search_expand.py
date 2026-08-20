"""hybrid paper search projections (expand)

Revision ID: f15a6d4273c14bd4ad7ec7780cf765e0
Revises: 4d8c9e5ab761
Create Date: 2026-08-20 12:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

revision: str = "f15a6d4273c14bd4ad7ec7780cf765e0"
down_revision: str | None = "4d8c9e5ab761"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add independently backfillable fuzzy and semantic search projections."""
    op.add_column(
        "documents",
        sa.Column(
            "search_text_compact",
            sa.Text(),
            sa.Computed(
                "regexp_replace("
                "lower(coalesce(title, '') || ' ' || coalesce(doi, '')), "
                "'[^[:alnum:]]', '', 'g'"
                ")",
                persisted=True,
            ),
            nullable=True,
        ),
        schema="scholens",
    )
    op.create_index(
        "ix_documents_search_text_compact_trgm",
        "documents",
        ["search_text_compact"],
        unique=False,
        schema="scholens",
        postgresql_using="gin",
        postgresql_ops={"search_text_compact": "gin_trgm_ops"},
    )
    op.create_table(
        "document_search_embeddings",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("model_revision", sa.String(length=128), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.Vector(dim=384),
            nullable=False,
        ),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["scholens.documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "model_revision"),
        schema="scholens",
    )
    op.create_index(
        "ix_document_search_embeddings_revision",
        "document_search_embeddings",
        ["model_revision"],
        unique=False,
        schema="scholens",
    )
    op.create_index(
        "ix_document_search_embeddings_hnsw_cosine",
        "document_search_embeddings",
        ["embedding"],
        unique=False,
        schema="scholens",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
