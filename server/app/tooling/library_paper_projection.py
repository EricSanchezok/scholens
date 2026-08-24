"""Bounded model-facing projections for personal Library paper tools."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from app.modules.papers.application.contracts.documents import (
    DocumentMetadataOverrides,
    DocumentResponse,
    LibraryPaperResponse,
    LibraryPaperTagResponse,
)
from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.papers.application.summary_limits import (
    LIBRARY_PAPER_KEYWORD_JSON_BYTES,
    LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS,
    LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
    LIBRARY_PAPER_MAX_AUTHORS,
    LIBRARY_PAPER_MAX_CITATIONS,
    LIBRARY_PAPER_MAX_INSTITUTIONS,
    LIBRARY_PAPER_MAX_KEYWORDS,
    LIBRARY_PAPER_MAX_STARTER_QUESTIONS,
    LIBRARY_PAPER_MAX_TAGS,
    LIBRARY_PAPER_TEXT_JSON_BYTES,
)
from app.shared.domain import JsonValue
from app.tooling import workspace_contracts as wc
from app.tooling.bounded_projection import (
    bounded_optional_text,
    bounded_text,
    bounded_text_list,
)
from app.tooling.contracts import ToolOutcome, ToolResourceLink
from pydantic import ValidationError

LIBRARY_PAPER_GUIDANCE = (
    "This is a bounded preview. Use get_library_paper_page with the document_id "
    "for lossless durable Library and document JSON."
)
LIBRARY_PAPER_LIST_GUIDANCE = (
    "Items are bounded previews. Continue with next_cursor when present and use "
    "get_library_paper_page with a document_id for lossless durable JSON. Active "
    "ingestions are reported by list_jobs, outside this durable-paper keyset."
)


@dataclass(frozen=True, slots=True)
class LibraryPaperProjection:
    value: LibraryPaperResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class DocumentProjection:
    value: DocumentResponse
    content_truncated: bool


def _project_tags(
    values: list[LibraryPaperTagResponse],
) -> tuple[list[LibraryPaperTagResponse], bool]:
    page = values[:LIBRARY_PAPER_MAX_TAGS]
    projected: list[LibraryPaperTagResponse] = []
    truncated = len(page) != len(values)
    for value in page:
        name, name_truncated = bounded_text(
            value.name,
            max_bytes=LIBRARY_PAPER_KEYWORD_JSON_BYTES,
        )
        color, color_truncated = bounded_optional_text(
            value.color,
            max_bytes=LIBRARY_PAPER_KEYWORD_JSON_BYTES,
        )
        projected.append(value.model_copy(update={"name": name, "color": color}))
        truncated = truncated or name_truncated or color_truncated
    return projected, truncated


def _project_metadata_overrides(
    value: DocumentMetadataOverrides,
) -> tuple[DocumentMetadataOverrides, bool]:
    title, title_truncated = bounded_optional_text(
        value.title,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    abstract, abstract_truncated = bounded_optional_text(
        value.abstract,
        max_bytes=LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
    )
    authors, authors_truncated = bounded_text_list(
        value.authors,
        max_items=LIBRARY_PAPER_MAX_AUTHORS,
        item_max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    )
    institutions, institutions_truncated = bounded_text_list(
        value.institutions,
        max_items=LIBRARY_PAPER_MAX_INSTITUTIONS,
        item_max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    )
    doi, doi_truncated = bounded_optional_text(
        value.doi,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    journal, journal_truncated = bounded_optional_text(
        value.journal,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    publisher, publisher_truncated = bounded_optional_text(
        value.publisher,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    return (
        value.model_copy(
            update={
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "institutions": institutions,
                "doi": doi,
                "journal": journal,
                "publisher": publisher,
            }
        ),
        any(
            (
                title_truncated,
                abstract_truncated,
                authors_truncated,
                institutions_truncated,
                doi_truncated,
                journal_truncated,
                publisher_truncated,
            )
        ),
    )


def _project_citations(
    values: list[ResponseCitation] | None,
) -> tuple[list[ResponseCitation] | None, bool]:
    if values is None:
        return None, False
    page = values[:LIBRARY_PAPER_MAX_CITATIONS]
    projected: list[ResponseCitation] = []
    truncated = len(page) != len(values)
    for value in page:
        text, text_truncated = bounded_text(
            value.text,
            max_bytes=LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        )
        document_id, id_truncated = bounded_optional_text(
            value.document_id,
            max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
        )
        projected.append(
            value.model_copy(update={"text": text, "document_id": document_id})
        )
        truncated = truncated or text_truncated or id_truncated
    return projected, truncated


def project_document(value: DocumentResponse) -> DocumentProjection:
    original_filename, filename_truncated = bounded_text(
        value.original_filename,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    mime_type, mime_truncated = bounded_text(
        value.mime_type,
        max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    )
    title, title_truncated = bounded_optional_text(
        value.title,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    abstract, abstract_truncated = bounded_optional_text(
        value.abstract,
        max_bytes=LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
    )
    summary, summary_truncated = bounded_optional_text(
        value.summary,
        max_bytes=LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
    )
    authors, authors_truncated = bounded_text_list(
        value.authors,
        max_items=LIBRARY_PAPER_MAX_AUTHORS,
        item_max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    )
    institutions, institutions_truncated = bounded_text_list(
        value.institutions,
        max_items=LIBRARY_PAPER_MAX_INSTITUTIONS,
        item_max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    )
    keywords, keywords_truncated = bounded_text_list(
        value.keywords,
        max_items=LIBRARY_PAPER_MAX_KEYWORDS,
        item_max_bytes=LIBRARY_PAPER_KEYWORD_JSON_BYTES,
    )
    doi, doi_truncated = bounded_optional_text(
        value.doi,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    journal, journal_truncated = bounded_optional_text(
        value.journal,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    publisher, publisher_truncated = bounded_optional_text(
        value.publisher,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    citations, citations_truncated = _project_citations(value.summary_citations)
    starters, starters_truncated = bounded_text_list(
        value.starter_questions,
        max_items=LIBRARY_PAPER_MAX_STARTER_QUESTIONS,
        item_max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    parser_quality, parser_quality_truncated = bounded_optional_text(
        value.parser_quality,
        max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    )
    parser_warning, parser_warning_truncated = bounded_optional_text(
        value.parser_warning_code,
        max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    )
    return DocumentProjection(
        value=value.model_copy(
            update={
                "original_filename": original_filename,
                "mime_type": mime_type,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "institutions": institutions,
                "keywords": keywords,
                "doi": doi,
                "journal": journal,
                "publisher": publisher,
                "summary": summary,
                "summary_citations": citations,
                "starter_questions": starters,
                "parser_quality": parser_quality,
                "parser_warning_code": parser_warning,
            }
        ),
        content_truncated=any(
            (
                filename_truncated,
                mime_truncated,
                title_truncated,
                abstract_truncated,
                summary_truncated,
                authors_truncated,
                institutions_truncated,
                keywords_truncated,
                doi_truncated,
                journal_truncated,
                publisher_truncated,
                citations_truncated,
                starters_truncated,
                parser_quality_truncated,
                parser_warning_truncated,
            )
        ),
    )


def project_library_paper(value: LibraryPaperResponse) -> LibraryPaperProjection:
    overrides, overrides_truncated = _project_metadata_overrides(
        value.metadata_overrides
    )
    document_projection = project_document(value.document)
    tags, tags_truncated = _project_tags(value.tags)
    return LibraryPaperProjection(
        value=value.model_copy(
            update={
                "metadata_overrides": overrides,
                "preview_url": None,
                "tags": tags,
                "document": document_projection.value,
            }
        ),
        content_truncated=(
            overrides_truncated
            or document_projection.content_truncated
            or tags_truncated
            or value.preview_url is not None
        ),
    )


def _paper_resource_link(value: LibraryPaperResponse) -> ToolResourceLink:
    document_id = value.document.document_id
    name, _ = bounded_text(
        value.document.title or f"Paper {document_id}",
        max_bytes=512,
    )
    return ToolResourceLink(
        uri=f"scholens://papers/{document_id}",
        name=name,
        description=(
            "Canonical Scholens paper metadata. Use get_paper_content for bounded text."
        ),
    )


def project_updated_library_paper(outcome: ToolOutcome) -> ToolOutcome:
    """Apply the bounded update contract to fresh and persisted legacy outcomes."""

    try:
        tool_value = wc.LibraryPaperToolOutput.model_validate(outcome.payload)
    except ValidationError:
        value = LibraryPaperResponse.model_validate(outcome.payload)
        prior_content_truncated = False
    else:
        value = LibraryPaperResponse.model_validate(
            tool_value.model_dump(
                mode="python",
                include=set(LibraryPaperResponse.model_fields),
            )
        )
        prior_content_truncated = tool_value.content_truncated

    projection = project_library_paper(value)
    content_truncated = prior_content_truncated or projection.content_truncated
    payload = wc.LibraryPaperToolOutput(
        **projection.value.model_dump(),
        content_truncated=content_truncated,
        guidance=LIBRARY_PAPER_GUIDANCE,
    )
    action: dict[str, JsonValue] = {
        "kind": "library_paper_updated",
        "library_entry_id": str(projection.value.library_entry_id),
        "document_id": str(projection.value.document.document_id),
        "status": projection.value.status.value,
        "content_truncated": content_truncated,
    }
    return replace(
        outcome,
        payload=cast(JsonValue, payload.model_dump(mode="json")),
        sources=(),
        artifacts=[],
        action=action,
        resource_links=(_paper_resource_link(projection.value),),
    )


__all__ = [
    "LIBRARY_PAPER_GUIDANCE",
    "LIBRARY_PAPER_LIST_GUIDANCE",
    "LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS",
    "LibraryPaperProjection",
    "DocumentProjection",
    "project_library_paper",
    "project_updated_library_paper",
    "project_document",
]
