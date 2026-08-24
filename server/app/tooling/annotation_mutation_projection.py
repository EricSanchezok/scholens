"""Bounded receipts for annotation mutations with independently readable content."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    ResearchCreatorResponse,
    ResearchItemResponse,
)
from app.tooling.bounded_projection import bounded_optional_text
from app.shared.application.text import json_bounded_prefix

ANNOTATION_MUTATION_PREVIEW_JSON_BYTES = 4 * 1024
ANNOTATION_MUTATION_IDENTITY_JSON_BYTES = 128


@dataclass(frozen=True, slots=True)
class AnnotationCommentProjection:
    comment: AnnotationCommentResponse
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class AnnotationThreadProjection:
    thread: ResearchItemResponse
    content_truncated: bool


def _project_creator(
    creator: ResearchCreatorResponse,
) -> tuple[ResearchCreatorResponse, bool]:
    display_name, truncated = bounded_optional_text(
        creator.display_name,
        max_bytes=ANNOTATION_MUTATION_IDENTITY_JSON_BYTES,
    )
    return creator.model_copy(update={"display_name": display_name}), truncated


def project_annotation_comment(
    comment: AnnotationCommentResponse,
) -> AnnotationCommentProjection:
    preview = json_bounded_prefix(
        comment.content,
        max_bytes=ANNOTATION_MUTATION_PREVIEW_JSON_BYTES,
    )
    created_by, creator_truncated = _project_creator(comment.created_by)
    return AnnotationCommentProjection(
        comment=comment.model_copy(
            update={"content": preview, "created_by": created_by}
        ),
        content_truncated=preview != comment.content or creator_truncated,
    )


def project_annotation_thread(
    thread: ResearchItemResponse,
) -> AnnotationThreadProjection:
    content = thread.annotation_thread
    if content is None:  # pragma: no cover - owning capability invariant
        raise ValueError("annotation mutation returned a non-annotation item")
    quote_preview = json_bounded_prefix(
        content.quote_text,
        max_bytes=ANNOTATION_MUTATION_PREVIEW_JSON_BYTES,
    )
    created_by, creator_truncated = _project_creator(thread.created_by)
    resolved_by = content.resolved_by
    resolved_by_truncated = False
    if resolved_by is not None:
        resolved_by, resolved_by_truncated = _project_creator(resolved_by)
    content_truncated = (
        quote_preview != content.quote_text
        or content.position is not None
        or bool(content.comments)
        or creator_truncated
        or resolved_by_truncated
    )
    projected_content = content.model_copy(
        update={
            "quote_text": quote_preview,
            "position": None,
            "resolved_by": resolved_by,
            "comments": [],
        }
    )
    return AnnotationThreadProjection(
        thread=thread.model_copy(
            update={
                "created_by": created_by,
                "annotation_thread": projected_content,
            }
        ),
        content_truncated=content_truncated,
    )


__all__ = [
    "ANNOTATION_MUTATION_PREVIEW_JSON_BYTES",
    "ANNOTATION_MUTATION_IDENTITY_JSON_BYTES",
    "AnnotationCommentProjection",
    "AnnotationThreadProjection",
    "project_annotation_comment",
    "project_annotation_thread",
]
