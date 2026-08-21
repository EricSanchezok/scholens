"""Annotation responses enriched with authorized profile avatars."""

from datetime import datetime
from uuid import UUID

from app.modules.research.application.contracts import (
    AnnotationAudience,
    AnnotationCommentResponse,
    AnnotationThreadCapabilities,
    ResearchCreatorResponse,
)
from app.modules.research.application.positions import ResearchPosition
from app.shared.application import AvatarReference
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
)
from pydantic import BaseModel


class AvatarResearchCreatorResponse(ResearchCreatorResponse):
    avatar: AvatarReference | None = None


class AvatarAnnotationCommentResponse(AnnotationCommentResponse):
    created_by: AvatarResearchCreatorResponse


class AvatarAnnotationThreadSummaryResponse(BaseModel):
    id: UUID
    audience: AnnotationAudience
    target_document_id: UUID
    created_by: AvatarResearchCreatorResponse
    created_at: datetime
    quote_text: str
    position: ResearchPosition | None
    color: AnnotationColor
    role: str
    mode: AnnotationThreadMode
    comment_count: int
    last_activity_at: datetime
    status: AnnotationThreadStatus
    resolved_by: AvatarResearchCreatorResponse | None
    resolved_at: datetime | None
    capabilities: AnnotationThreadCapabilities
    comments: list[AvatarAnnotationCommentResponse]


class AvatarAnnotationThreadListResponse(BaseModel):
    items: list[AvatarAnnotationThreadSummaryResponse]
    next_cursor: str | None = None


__all__ = [
    "AvatarAnnotationCommentResponse",
    "AvatarAnnotationThreadListResponse",
    "AvatarAnnotationThreadSummaryResponse",
    "AvatarResearchCreatorResponse",
]
