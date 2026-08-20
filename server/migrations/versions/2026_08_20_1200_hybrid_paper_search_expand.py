"""hybrid paper search projections (expand)

Revision ID: f15a6d4273c14bd4ad7ec7780cf765e0
Revises: 8a8f20189e5c45c5aceb09eb45dd8e87
Create Date: 2026-08-20 12:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

revision: str = "f15a6d4273c14bd4ad7ec7780cf765e0"
down_revision: str | None = "8a8f20189e5c45c5aceb09eb45dd8e87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add independently backfillable fuzzy and semantic search projections."""
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')
               OR NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')
            THEN
                RAISE EXCEPTION 'pg_trgm and vector extensions must be installed by the database owner';
            END IF;
        END
        $$
        """
    )
    op.add_column(
        "documents",
        sa.Column(
            "search_text_compact",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        schema="scholens",
    )
    op.execute(
        """
        UPDATE scholens.documents
        SET search_text_compact = regexp_replace(
            lower(
                coalesce(title, '') || ' ' ||
                coalesce(array_to_string(authors, ' '), '') || ' ' ||
                coalesce(doi, '')
            ),
            '[^[:alnum:]]', '', 'g'
        )
        """
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
    op.execute(
        """
        CREATE INDEX ix_document_search_embeddings_hnsw_cosine
        ON scholens.document_search_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scholens.document_content_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_text_compact := regexp_replace(
                lower(
                    coalesce(NEW.title, '') || ' ' ||
                    coalesce(array_to_string(NEW.authors, ' '), '') || ' ' ||
                    coalesce(NEW.doi, '')
                ),
                '[^[:alnum:]]', '', 'g'
            );
            NEW.ts_vector :=
                setweight(to_tsvector('pg_catalog.english', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('pg_catalog.english', coalesce(array_to_string(NEW.authors, ' '), '')), 'A') ||
                setweight(to_tsvector('pg_catalog.english', coalesce(array_to_string(NEW.keywords, ' '), '')), 'B') ||
                setweight(to_tsvector('pg_catalog.english', coalesce(NEW.summary, '')), 'B') ||
                setweight(to_tsvector('pg_catalog.english', coalesce(NEW.abstract, '')), 'C') ||
                setweight(to_tsvector('pg_catalog.english', coalesce(NEW.raw_content, '')), 'D');
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("UPDATE scholens.documents SET title = title")
