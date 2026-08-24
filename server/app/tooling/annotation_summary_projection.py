"""Bounded MCP projections for annotation-thread collection summaries."""

from __future__ import annotations

from app.modules.research.application.contracts import (
    AnnotationThreadSummaryResponse,
    ResearchCreatorResponse,
)
from app.modules.research.application.annotation_summaries import (
    ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES,
    ANNOTATION_SUMMARY_MAX_PAGE_ITEMS,
    ANNOTATION_SUMMARY_QUOTE_JSON_BYTES,
    bounded_annotation_display_name,
    bounded_annotation_quote,
)
from app.modules.research.application.positions import PdfTextPosition, ResearchPosition


def _bounded_creator(
    value: ResearchCreatorResponse | None,
) -> ResearchCreatorResponse | None:
    if value is None or value.display_name is None:
        return value
    return value.model_copy(
        update={"display_name": bounded_annotation_display_name(value.display_name)}
    )


def _compact_position(value: ResearchPosition | None) -> ResearchPosition | None:
    if not isinstance(value, PdfTextPosition):
        return value
    return value.model_copy(
        update={
            "rects": value.rects[:1],
            "segments": None,
        }
    )


def project_annotation_summary(
    value: AnnotationThreadSummaryResponse,
) -> AnnotationThreadSummaryResponse:
    """Retain list-decision fields without copying complete discussion content."""

    return value.model_copy(
        update={
            "created_by": _bounded_creator(value.created_by),
            "quote_text": bounded_annotation_quote(value.quote_text),
            "position": _compact_position(value.position),
            "resolved_by": _bounded_creator(value.resolved_by),
            "comments": [],
        }
    )


__all__ = [
    "ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES",
    "ANNOTATION_SUMMARY_MAX_PAGE_ITEMS",
    "ANNOTATION_SUMMARY_QUOTE_JSON_BYTES",
    "project_annotation_summary",
]
