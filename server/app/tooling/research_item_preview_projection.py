"""Small previews for typed MCP Resource manifests of complete research items."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.research.application.contracts import (
    AudioOverviewContent,
    CitationContent,
    DataTableContent,
    ResearchCreatorResponse,
    ResearchItemResponse,
)
from app.shared.application.text import json_bounded_prefix
from app.tooling.annotation_mutation_projection import project_annotation_thread

_PREVIEW_TEXT_JSON_BYTES = 4 * 1024
_FIELD_JSON_BYTES = 512
_IDENTITY_JSON_BYTES = 128
_MAX_LIST_ITEMS = 8


@dataclass(frozen=True, slots=True)
class ResearchItemPreviewProjection:
    value: ResearchItemResponse
    content_truncated: bool


def _text(value: str, *, max_bytes: int) -> tuple[str, bool]:
    bounded = json_bounded_prefix(value, max_bytes=max_bytes)
    return bounded, bounded != value


def _optional_text(
    value: str | None,
    *,
    max_bytes: int,
) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    return _text(value, max_bytes=max_bytes)


def _creator(value: ResearchCreatorResponse) -> tuple[ResearchCreatorResponse, bool]:
    display_name, truncated = _optional_text(
        value.display_name,
        max_bytes=_IDENTITY_JSON_BYTES,
    )
    return value.model_copy(update={"display_name": display_name}), truncated


def _text_list(values: list[str]) -> tuple[list[str], bool]:
    projected: list[str] = []
    truncated = len(values) > _MAX_LIST_ITEMS
    for value in values[:_MAX_LIST_ITEMS]:
        bounded, item_truncated = _text(value, max_bytes=_FIELD_JSON_BYTES)
        projected.append(bounded)
        truncated = truncated or item_truncated
    return projected, truncated


def _citation(value: CitationContent) -> tuple[CitationContent, bool]:
    snapshot = value.snapshot
    data = snapshot.data
    title, title_truncated = _optional_text(
        data.title,
        max_bytes=_PREVIEW_TEXT_JSON_BYTES,
    )
    authors, authors_truncated = _text_list(data.authors)
    updates: dict[str, object] = {"title": title, "authors": authors}
    truncated = title_truncated or authors_truncated
    for field_name in ("document_id", "publish_date", "journal", "publisher", "doi"):
        field_value = getattr(data, field_name)
        bounded, field_truncated = _optional_text(
            field_value,
            max_bytes=_FIELD_JSON_BYTES,
        )
        updates[field_name] = bounded
        truncated = truncated or field_truncated
    preferred_style, preferred_truncated = _text(
        snapshot.preferred_style,
        max_bytes=100,
    )
    style_display, display_truncated = _text(
        snapshot.style_display,
        max_bytes=200,
    )
    missing_fields, missing_truncated = _text_list(snapshot.missing_fields)
    projected_snapshot = snapshot.model_copy(
        update={
            "preferred_style": preferred_style,
            "style_display": style_display,
            "data": data.model_copy(update=updates),
            "missing_fields": missing_fields,
        }
    )
    return (
        value.model_copy(update={"snapshot": projected_snapshot}),
        truncated or preferred_truncated or display_truncated or missing_truncated,
    )


def _response_citations(
    values: list[ResponseCitation],
) -> tuple[list[ResponseCitation], bool]:
    projected: list[ResponseCitation] = []
    truncated = len(values) > _MAX_LIST_ITEMS
    for value in values[:_MAX_LIST_ITEMS]:
        text, text_truncated = _text(value.text, max_bytes=_FIELD_JSON_BYTES)
        document_id, document_truncated = _optional_text(
            value.document_id,
            max_bytes=_IDENTITY_JSON_BYTES,
        )
        projected.append(
            value.model_copy(update={"text": text, "document_id": document_id})
        )
        truncated = truncated or text_truncated or document_truncated
    return projected, truncated


def _audio(value: AudioOverviewContent) -> tuple[AudioOverviewContent, bool]:
    title, title_truncated = _optional_text(
        value.title,
        max_bytes=_FIELD_JSON_BYTES,
    )
    transcript, transcript_truncated = _text(
        value.transcript,
        max_bytes=_PREVIEW_TEXT_JSON_BYTES,
    )
    citations, citations_truncated = _response_citations(value.citations)
    audio_url, url_truncated = _text(value.audio_url, max_bytes=1_024)
    voice_id, voice_truncated = _text(value.voice_id, max_bytes=_IDENTITY_JSON_BYTES)
    model_version, model_truncated = _text(
        value.model_version,
        max_bytes=_IDENTITY_JSON_BYTES,
    )
    return (
        value.model_copy(
            update={
                "title": title,
                "transcript": transcript,
                "citations": citations,
                "audio_url": audio_url,
                "voice_id": voice_id,
                "model_version": model_version,
            }
        ),
        any(
            (
                title_truncated,
                transcript_truncated,
                citations_truncated,
                url_truncated,
                voice_truncated,
                model_truncated,
            )
        ),
    )


def _data_table(value: DataTableContent) -> tuple[DataTableContent, bool]:
    title, title_truncated = _optional_text(
        value.title,
        max_bytes=_FIELD_JSON_BYTES,
    )
    columns, columns_truncated = _text_list(value.columns)
    row_failures, failures_truncated = _text_list(value.row_failures)
    content_omitted = bool(value.rows) or bool(value.citations)
    return (
        value.model_copy(
            update={
                "title": title,
                "columns": columns,
                "rows": [],
                "citations": [],
                "row_failures": row_failures,
            }
        ),
        title_truncated or columns_truncated or failures_truncated or content_omitted,
    )


def project_research_item_preview(
    value: ResearchItemResponse,
) -> ResearchItemPreviewProjection:
    """Retain item identity and a useful preview; page tools own full content."""

    if value.annotation_thread is not None:
        projection = project_annotation_thread(value)
        return ResearchItemPreviewProjection(
            value=projection.thread,
            content_truncated=projection.content_truncated,
        )
    creator, creator_truncated = _creator(value.created_by)
    updates: dict[str, object] = {"created_by": creator}
    if value.citation is not None:
        citation, content_truncated = _citation(value.citation)
        updates["citation"] = citation
    elif value.audio_overview is not None:
        audio, content_truncated = _audio(value.audio_overview)
        updates["audio_overview"] = audio
    elif value.data_table is not None:
        data_table, content_truncated = _data_table(value.data_table)
        updates["data_table"] = data_table
    else:  # pragma: no cover - ResearchItemResponse enforces exactly one payload
        raise ValueError("research item content is missing")
    return ResearchItemPreviewProjection(
        value=value.model_copy(
            update=updates,
        ),
        content_truncated=creator_truncated or content_truncated,
    )


__all__ = ["ResearchItemPreviewProjection", "project_research_item_preview"]
