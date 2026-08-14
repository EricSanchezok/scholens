"""Cross-module cleanup for personal data removed with a Library membership."""

from __future__ import annotations

from uuid import UUID

from app.database.models import ResearchItem
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind
from sqlalchemy import delete
from sqlalchemy.orm import Session


def delete_personal_document_annotations(
    db: Session,
    *,
    document_id: UUID,
    user_id: int,
) -> None:
    """Delete only the actor's personal annotation layer for one Document."""
    db.execute(
        delete(ResearchItem).where(
            ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
            ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
            ResearchItem.created_by_id == user_id,
            ResearchItem.target_document_id == document_id,
        )
    )


__all__ = ["delete_personal_document_annotations"]
