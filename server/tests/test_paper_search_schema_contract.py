from app.modules.papers.infrastructure.models import (
    Document,
    DocumentSearchEmbedding,
)


def test_paper_search_projection_metadata_matches_migration_contract() -> None:
    embedding_columns = DocumentSearchEmbedding.__table__.c
    assert {"created_at", "updated_at", "indexed_at"}.issubset(embedding_columns.keys())

    compact_search_index = next(
        index
        for index in Document.__table__.indexes
        if index.name == "ix_documents_search_text_compact_trgm"
    )
    assert compact_search_index.dialect_options["postgresql"]["using"] == "gin"
    assert compact_search_index.dialect_options["postgresql"]["ops"] == {
        "search_text_compact": "gin_trgm_ops"
    }
