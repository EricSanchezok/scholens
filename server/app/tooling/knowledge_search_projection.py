"""Bounded public projection helpers for Scholens knowledge search."""

from __future__ import annotations

from app.modules.research.application.positions import (
    ParsedTextPosition,
    PdfTextPosition,
    ResearchPosition,
)
from app.shared.application.text import json_bounded_prefix
from app.shared.domain import JsonValue

KNOWLEDGE_SEARCH_MAX_PAGE_ITEMS = 25
KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT = 25
KNOWLEDGE_SEARCH_EXCERPT_JSON_BYTES = 512
KNOWLEDGE_SEARCH_SOURCE_JSON_BYTES = 256
KNOWLEDGE_SEARCH_TITLE_JSON_BYTES = 256


def bounded_knowledge_excerpt(value: str) -> str:
    """Return a search excerpt with a bounded encoded JSON representation."""

    return json_bounded_prefix(
        value,
        max_bytes=KNOWLEDGE_SEARCH_EXCERPT_JSON_BYTES,
    )


def bounded_knowledge_source(value: str) -> str:
    """Return the smaller evidence copy used in ``ToolOutcome.sources``."""

    return json_bounded_prefix(
        value,
        max_bytes=KNOWLEDGE_SEARCH_SOURCE_JSON_BYTES,
    )


def bounded_knowledge_title(value: str | None) -> str | None:
    if value is None:
        return None
    return json_bounded_prefix(
        value,
        max_bytes=KNOWLEDGE_SEARCH_TITLE_JSON_BYTES,
    )


def compact_knowledge_locator(
    position: ResearchPosition | None,
) -> dict[str, JsonValue] | None:
    """Project an annotation anchor without copying full PDF rectangle geometry."""

    if isinstance(position, ParsedTextPosition):
        locator: dict[str, JsonValue] = {
            "kind": position.kind,
            "start_offset": position.start_offset,
            "end_offset": position.end_offset,
        }
        if position.page_number is not None:
            locator["page_number"] = position.page_number
        return locator
    if isinstance(position, PdfTextPosition):
        return {
            "kind": position.kind,
            "page_number": position.page_number,
        }
    return None


__all__ = [
    "KNOWLEDGE_SEARCH_MAX_PAGE_ITEMS",
    "KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT",
    "bounded_knowledge_excerpt",
    "bounded_knowledge_source",
    "bounded_knowledge_title",
    "compact_knowledge_locator",
]
