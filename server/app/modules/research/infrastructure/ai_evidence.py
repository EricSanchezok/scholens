"""Transactional personal evidence deduplication, including legacy adoption."""

from uuid import UUID

from scholens_ai import EvidenceAnchor
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.research.infrastructure.models import (
    AiAnnotationEvidence,
    AnnotationThread,
    ResearchItem,
)


class AiEvidenceRepository:
    def reserve(
        self,
        db: Session,
        *,
        document_id: UUID,
        user_id: int,
        content_digest: str,
        anchor: EvidenceAnchor,
        segment_id: str | None,
        source_job_id: UUID | None,
        execution_generation: int | None,
    ) -> bool:
        # Adopt only a matching personal assistant anchor. User comments,
        # project annotations and other users' highlights never suppress work.
        legacy_id = db.scalar(
            select(ResearchItem.id)
            .join(
                AnnotationThread, AnnotationThread.research_item_id == ResearchItem.id
            )
            .where(
                ResearchItem.target_document_id == document_id,
                ResearchItem.created_by_id == user_id,
                ResearchItem.audience_type == "personal",
                AnnotationThread.role == "assistant",
                AnnotationThread.start_offset == anchor.start,
                AnnotationThread.end_offset == anchor.end,
                AnnotationThread.quote_text == anchor.quote,
            )
            .order_by(ResearchItem.id)
            .limit(1)
        )
        inserted = db.scalar(
            insert(AiAnnotationEvidence)
            .values(
                user_id=user_id,
                document_id=document_id,
                content_digest=content_digest,
                evidence_digest=anchor.digest,
                research_item_id=legacy_id,
                source_job_id=source_job_id,
                execution_generation=execution_generation,
                segment_id=segment_id,
                start_offset=anchor.start,
                end_offset=anchor.end,
            )
            .on_conflict_do_nothing()
            .returning(AiAnnotationEvidence.evidence_digest)
        )
        return inserted is not None and legacy_id is None

    def attach(
        self,
        db: Session,
        *,
        document_id: UUID,
        user_id: int,
        content_digest: str,
        evidence_digest: str,
        research_item_id: UUID,
    ) -> None:
        db.execute(
            update(AiAnnotationEvidence)
            .where(
                AiAnnotationEvidence.document_id == document_id,
                AiAnnotationEvidence.user_id == user_id,
                AiAnnotationEvidence.content_digest == content_digest,
                AiAnnotationEvidence.evidence_digest == evidence_digest,
            )
            .values(research_item_id=research_item_id)
        )


ai_evidence_repository = AiEvidenceRepository()
