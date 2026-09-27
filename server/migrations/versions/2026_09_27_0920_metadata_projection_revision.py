"""Version metadata projections without invalidating them on unrelated writes."""

from alembic import op
import sqlalchemy as sa

revision = "2026_09_27_1500"
down_revision = "2026_09_27_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "search_revision",
            sa.BigInteger(),
            nullable=True,
            server_default=sa.text("0"),
        ),
        schema="scholens",
    )
    op.add_column(
        "document_search_embeddings",
        sa.Column("source_revision", sa.BigInteger(), nullable=True),
        schema="scholens",
    )
    op.execute("""
        CREATE FUNCTION scholens.document_search_revision_trigger() RETURNS trigger AS $$
        BEGIN
            IF ROW(NEW.title, NEW.keywords, NEW.summary, NEW.abstract)
                IS DISTINCT FROM ROW(OLD.title, OLD.keywords, OLD.summary, OLD.abstract)
            THEN
                NEW.search_revision := COALESCE(OLD.search_revision, 0) + 1;
            ELSE
                NEW.search_revision := COALESCE(OLD.search_revision, 0);
            END IF;
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER document_search_revision
            BEFORE UPDATE ON scholens.documents
            FOR EACH ROW EXECUTE FUNCTION scholens.document_search_revision_trigger()
    """)


def downgrade() -> None:
    raise RuntimeError("Forward-only migration: preserve N-1 metadata writers")
