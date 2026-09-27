"""token projection source revisions

Revision ID: 2026_09_27_1300
Revises: 2026_09_27_1200
Create Date: 2026-09-27 06:50:45.452269+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "2026_09_27_1300"
down_revision: Union[str, None] = "2026_09_27_1200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "document_token_projections",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("model_revision", sa.String(length=128), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("chunk_revision", sa.String(length=80), nullable=False),
        sa.Column("passage_count", sa.Integer(), nullable=False),
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
            "passage_count BETWEEN 0 AND 10000", name="ck_token_projection_count"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["scholens.documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("document_id", "model_revision"),
        schema="scholens",
    )
    op.create_table(
        "document_token_passages",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("model_revision", sa.String(length=128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("ts_vector", postgresql.TSVECTOR(), nullable=True),
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
            "ordinal >= 0 AND start_offset >= 0 AND end_offset > start_offset",
            name="ck_token_passage_offsets",
        ),
        sa.CheckConstraint(
            "start_line >= 1 AND end_line >= start_line AND token_count BETWEEN 1 AND 256",
            name="ck_token_passage_coordinates",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "model_revision"],
            [
                "scholens.document_token_projections.document_id",
                "scholens.document_token_projections.model_revision",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "model_revision", "ordinal"),
        schema="scholens",
    )
    op.create_index(
        "ix_document_token_passages_embedding_hnsw",
        "document_token_passages",
        ["embedding"],
        unique=False,
        schema="scholens",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_document_token_passages_ts_vector",
        "document_token_passages",
        ["ts_vector"],
        unique=False,
        schema="scholens",
        postgresql_using="gin",
    )
    op.add_column(
        "documents",
        sa.Column("content_digest", sa.String(length=64), nullable=True),
        schema="scholens",
    )
    op.execute("""
        CREATE FUNCTION scholens.document_source_revision_trigger() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                NEW.content_digest := encode(sha256(convert_to(NEW.raw_content, 'UTF8')), 'hex');
            ELSIF NEW.raw_content IS DISTINCT FROM OLD.raw_content
                OR OLD.content_digest IS NULL
                OR NEW.content_digest IS DISTINCT FROM OLD.content_digest THEN
                NEW.content_digest := encode(sha256(convert_to(NEW.raw_content, 'UTF8')), 'hex');
            END IF;
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER document_source_revision
            BEFORE INSERT OR UPDATE ON scholens.documents
            FOR EACH ROW EXECUTE FUNCTION scholens.document_source_revision_trigger()
    """)
    op.execute("""
        CREATE TRIGGER document_token_passages_tsvectorupdate
            BEFORE INSERT OR UPDATE OF content ON scholens.document_token_passages
            FOR EACH ROW EXECUTE FUNCTION scholens.document_passages_tsvector_trigger()
    """)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scholens.document_content_trigger() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND
                ROW(NEW.title, NEW.authors, NEW.keywords, NEW.abstract, NEW.raw_content)
                IS NOT DISTINCT FROM
                ROW(OLD.title, OLD.authors, OLD.keywords, OLD.abstract, OLD.raw_content)
            THEN
                RETURN NEW;
            END IF;
            NEW.ts_vector :=
                setweight(
                    to_tsvector('pg_catalog.english', coalesce(NEW.title, '')),
                    'A'
                ) ||
                setweight(
                    to_tsvector(
                        'pg_catalog.english',
                        coalesce(array_to_string(NEW.authors, ' '), '')
                    ),
                    'A'
                ) ||
                setweight(
                    to_tsvector(
                        'pg_catalog.english',
                        coalesce(array_to_string(NEW.keywords, ' '), '')
                    ),
                    'B'
                ) ||
                setweight(
                    to_tsvector('pg_catalog.english', coalesce(NEW.abstract, '')),
                    'C'
                ) ||
                setweight(
                    to_tsvector('pg_catalog.english', coalesce(NEW.raw_content, '')),
                    'D'
                );
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    raise RuntimeError("Forward-only migration: preserve rollback projections")
