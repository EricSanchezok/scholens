"""Create deterministic personal AI annotation threads from parsed content."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.database.models import ResearchAudienceType, RoleType
from app.helpers.parser import get_start_page_from_offset
from app.llm.utils import find_offsets
from app.modules.papers.infrastructure.repository import document_repository
from app.bootstrap.adapters.research_repository import (
    AnnotationThreadCreate,
    research_repository,
)
from app.modules.papers.application.contracts.extraction import PaperMetadataExtraction
from app.modules.research.application.positions import ParsedTextPosition
from app.shared.application import Actor
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedDocumentContent:
    raw_content: str
    page_offsets: dict[int, tuple[int, int]]


@dataclass(frozen=True, slots=True)
class CreatedAiAnnotations:
    thread_ids: tuple[uuid.UUID, ...]
    comment_ids: tuple[uuid.UUID, ...]


def require_parsed_content(
    db: Session,
    *,
    document_id: uuid.UUID,
    user: Actor,
) -> ParsedDocumentContent:
    document = document_repository.find_accessible(
        db,
        document_id=document_id,
        user=user,
    )
    if document is None:
        raise ValueError("document_not_found")
    if not document.raw_content:
        raise ValueError("document_content_unavailable")
    offsets = (
        {
            page: (bounds[0], bounds[1])
            for page, bounds in document.page_offset_map.items()
            if len(bounds) >= 2
        }
        if document.page_offset_map
        else {}
    )
    return ParsedDocumentContent(
        raw_content=document.raw_content,
        page_offsets=offsets,
    )


def create_ai_annotations(
    db: Session,
    *,
    document_id: uuid.UUID,
    metadata: PaperMetadataExtraction,
    user: Actor,
) -> CreatedAiAnnotations:
    if research_repository.has_assistant_annotation(
        db,
        document_id=document_id,
        user_id=user.id,
    ):
        logger.info(
            "research.ai_annotations.duplicate_skipped",
            extra={"document_id": str(document_id)},
        )
        return CreatedAiAnnotations((), ())
    content = require_parsed_content(db, document_id=document_id, user=user)
    thread_ids: list[uuid.UUID] = []
    comment_ids: list[uuid.UUID] = []
    skipped = 0
    for highlight in metadata.highlights:
        offsets = find_offsets(highlight.text, content.raw_content)
        if offsets == (-1, -1):
            skipped += 1
            logger.warning(
                "research.ai_annotations.quote_not_found_skipped",
                extra={
                    "document_id": str(document_id),
                    "quote_chars": len(highlight.text),
                },
            )
            continue
        page_number = (
            get_start_page_from_offset(content.page_offsets, offsets[0])
            if content.page_offsets
            else None
        )
        item = research_repository.create_annotation_thread(
            db,
            document_id=document_id,
            user_id=user.id,
            create=AnnotationThreadCreate(
                quote_text=highlight.text,
                position=ParsedTextPosition(
                    start_offset=offsets[0],
                    end_offset=offsets[1],
                    page_number=page_number,
                ),
                color="blue",
                audience_type=ResearchAudienceType.PERSONAL,
                audience_project_id=None,
                content_role=RoleType.ASSISTANT,
                initial_comment=highlight.annotation,
            ),
            refresh_result=False,
        )
        thread_ids.append(item.id)
        if item.annotation_thread is None:
            raise RuntimeError("annotation_item_without_thread")
        comment_ids.extend(comment.id for comment in item.annotation_thread.comments)
    if skipped:
        logger.info(
            "research.ai_annotations.partial_skip",
            extra={
                "document_id": str(document_id),
                "skipped": skipped,
                "total": len(metadata.highlights),
            },
        )
    return CreatedAiAnnotations(
        thread_ids=tuple(thread_ids),
        comment_ids=tuple(comment_ids),
    )


__all__ = [
    "CreatedAiAnnotations",
    "ParsedDocumentContent",
    "create_ai_annotations",
    "require_parsed_content",
]
