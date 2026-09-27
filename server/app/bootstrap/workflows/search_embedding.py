"""Prepare optional query inference before opening a search transaction."""

import asyncio
import logging

from scholens_ai import configured_embedder, semantic_source_digest

from app.modules.papers.application.contracts.search import PaperSearchEmbedding

logger = logging.getLogger(__name__)


async def prepare_search_embedding(query: str) -> PaperSearchEmbedding | None:
    return await asyncio.to_thread(_prepare, query.strip())


def _prepare(query: str) -> PaperSearchEmbedding | None:
    selected = configured_embedder()
    if selected is None:
        return None
    try:
        return PaperSearchEmbedding(
            query_digest=semantic_source_digest(query),
            model_revision=selected.revision,
            vector=tuple(selected.embed_query(query)),
        )
    except Exception as exc:
        logger.warning(
            "paper.search.embedding_unavailable",
            extra={"exception_type": type(exc).__name__},
        )
        return None
