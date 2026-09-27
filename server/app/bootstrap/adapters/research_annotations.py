"""Create deterministic personal AI annotation threads from parsed content."""

from __future__ import annotations

import logging
import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session
from scholens_ai import resolve_evidence

from app.bootstrap.adapters.research_repository import (
    AnnotationThreadCreate,
    research_repository,
)
from app.database.models import Document, ResearchAudienceType, RoleType
from app.helpers.parser import get_start_page_from_offset
from app.modules.research.infrastructure.ai_evidence import ai_evidence_repository
from app.modules.papers.application.contracts.extraction import PaperMetadataExtraction
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_PARSED_CONTENT_COLUMNS,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.research.application.positions import ParsedTextPosition
from app.shared.application import Actor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedDocumentContent:
    raw_content: str
    page_offsets: dict[int, tuple[int, int]]


@dataclass(frozen=True, slots=True)
class CreatedAiAnnotations:
    thread_ids: tuple[uuid.UUID, ...]
    comment_ids: tuple[uuid.UUID, ...]
    total: int = 0
    anchored: int = 0
    already_present: int = 0
    skipped: int = 0


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
        document_columns=DOCUMENT_PARSED_CONTENT_COLUMNS,
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
    source_job_id: uuid.UUID | None = None,
    execution_generation: int | None = None,
) -> CreatedAiAnnotations:
    # Serialize with canonical text repair and annotation creation. All paths
    # lock the document before individual evidence/research rows.
    db.execute(select(Document.id).where(Document.id == document_id).with_for_update())
    content = require_parsed_content(db, document_id=document_id, user=user)
    content_digest = hashlib.sha256(content.raw_content.encode()).hexdigest()
    thread_ids: list[uuid.UUID] = []
    comment_ids: list[uuid.UUID] = []
    skipped = anchored = already_present = 0
    for highlight in metadata.highlights:
        resolution = resolve_evidence(
            content.raw_content,
            highlight.text,
            segment_id=highlight.segment_id,
            content_digest=content_digest,
        )
        anchor = resolution.anchor
        if anchor is None:
            skipped += 1
            logger.warning(
                "research.ai_annotations.quote_not_found_skipped",
                extra={
                    "document_id": str(document_id),
                    "quote_chars": len(highlight.text),
                    "reason": resolution.reason,
                },
            )
            continue
        anchored += 1
        if not ai_evidence_repository.reserve(
            db,
            document_id=document_id,
            user_id=user.id,
            content_digest=content_digest,
            anchor=anchor,
            segment_id=highlight.segment_id,
            source_job_id=source_job_id,
            execution_generation=execution_generation,
        ):
            already_present += 1
            continue
        page_number = (
            get_start_page_from_offset(content.page_offsets, anchor.start)
            if content.page_offsets
            else None
        )
        item = research_repository.create_annotation_thread(
            db,
            document_id=document_id,
            user_id=user.id,
            create=AnnotationThreadCreate(
                quote_text=anchor.quote,
                position=ParsedTextPosition(
                    start_offset=anchor.start,
                    end_offset=anchor.end,
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
        ai_evidence_repository.attach(
            db,
            document_id=document_id,
            user_id=user.id,
            content_digest=content_digest,
            evidence_digest=anchor.digest,
            research_item_id=item.id,
        )
        thread_ids.append(item.id)
        if item.annotation_thread is None:
            raise RuntimeError("annotation_item_without_thread")
        comment_ids.extend(comment.id for comment in item.annotation_thread.comments)
    logger.info(
        "research.ai_annotations.coverage",
        extra={
            "document_id": str(document_id),
            "skipped": skipped,
            "total": len(metadata.highlights),
            "anchored": anchored,
            "already_present": already_present,
            "annotations_created": len(thread_ids),
        },
    )
    return CreatedAiAnnotations(
        thread_ids=tuple(thread_ids),
        comment_ids=tuple(comment_ids),
        total=len(metadata.highlights),
        anchored=anchored,
        already_present=already_present,
        skipped=skipped,
    )


__all__ = [
    "CreatedAiAnnotations",
    "ParsedDocumentContent",
    "create_ai_annotations",
    "require_parsed_content",
]
