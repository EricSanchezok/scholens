from unittest.mock import MagicMock

import pytest
from scholens_ai import EMBEDDING_MODEL_REVISION, semantic_source_digest
from scholens_ai.inference_client import EmbeddingUnavailable

from app.bootstrap.workflows import search_embedding
from app.modules.papers.application.contracts.search import (
    PaperSearchEmbedding,
    PaperSearchRequest,
    PaperSearchResponse,
)
from app.transport.http.public_v1 import paper_search


@pytest.mark.asyncio
async def test_http_search_prepares_inference_before_opening_the_database(monkeypatch):
    events = []
    prepared = PaperSearchEmbedding(
        query_digest=semantic_source_digest("world models"),
        model_revision=EMBEDDING_MODEL_REVISION,
        vector=(1.0,) + (0.0,) * 383,
    )

    async def prepare(query):
        assert query == "world models"
        assert events == []
        events.append("inference")
        return prepared

    capabilities = MagicMock()
    capabilities.paper_search.return_value = PaperSearchResponse(items=[], total=0)
    executor = MagicMock()

    def query(callback):
        assert events == ["inference"]
        events.append("database")
        return callback(capabilities)

    executor.query.side_effect = query
    monkeypatch.setattr(paper_search, "prepare_search_embedding", prepare)
    monkeypatch.setattr(paper_search, "track_event", MagicMock())
    result = await paper_search.search_papers_endpoint(
        request=PaperSearchRequest(query="world models"),
        http_request=MagicMock(),
        executor=executor,
        current_user=MagicMock(id=1),
    )
    assert result.total == 0
    assert capabilities.paper_search.call_args.kwargs["embedding"] == prepared
    assert events == ["inference", "database"]


@pytest.mark.asyncio
async def test_inference_failure_leaves_lexical_search_available(monkeypatch):
    model = MagicMock()
    model.embed_query.side_effect = EmbeddingUnavailable("inference_deadline")
    monkeypatch.setattr(search_embedding, "configured_embedder", lambda: model)
    assert await search_embedding.prepare_search_embedding("query") is None


@pytest.mark.asyncio
async def test_knowledge_search_prepares_once_outside_its_transaction(monkeypatch):
    from app.tooling import workspace_handlers as handlers
    from app.tooling.contracts import ToolOutcome
    from app.tooling.workspace_contracts import (
        SearchKnowledgeInput,
        LibraryKnowledgeScope,
    )

    events = []

    async def prepare(query):
        events.append("inference")
        return None

    monkeypatch.setattr(handlers, "prepare_search_embedding", prepare)
    executor = MagicMock()

    def query(callback):
        assert events == ["inference"]
        events.append("database")
        return callback(MagicMock())

    executor.query.side_effect = query
    handler = handlers.WorkspaceToolHandlers(
        executor=executor,
        ingestion=MagicMock(),
        citations=MagicMock(),
        cursor_secret="test-secret",
        web_base_url="https://scholens.example",
    )
    handler.search_knowledge = MagicMock(return_value=ToolOutcome(payload={}))
    await handler.search_knowledge_workflow(
        MagicMock(),
        SearchKnowledgeInput(query="concepts", scope=LibraryKnowledgeScope()),
        "key",
        MagicMock(),
    )
    assert events == ["inference", "database"]
    handler.search_knowledge.assert_called_once()
