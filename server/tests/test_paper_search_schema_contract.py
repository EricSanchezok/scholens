from app.modules.papers.infrastructure.models import (
    Document,
    DocumentPassage,
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

    passage_columns = DocumentPassage.__table__.c
    assert {
        "embedding",
        "embedding_model_revision",
        "embedding_source_digest",
        "embedded_at",
    }.issubset(passage_columns.keys())
    passage_index = next(
        index
        for index in DocumentPassage.__table__.indexes
        if index.name == "ix_document_passages_embedding_hnsw_cosine"
    )
    assert passage_index.dialect_options["postgresql"]["using"] == "hnsw"
    assert passage_index.dialect_options["postgresql"]["ops"] == {
        "embedding": "vector_cosine_ops"
    }
