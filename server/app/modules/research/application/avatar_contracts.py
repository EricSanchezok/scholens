"""Annotation responses enriched with authorized profile avatars."""

from collections.abc import Sequence

from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    AnnotationThreadSummaryResponse,
    ResearchCreatorResponse,
)
from app.shared.application import AvatarReference
from pydantic import BaseModel


class AvatarResearchCreatorResponse(ResearchCreatorResponse):
    avatar: AvatarReference | None = None


class AvatarAnnotationCommentResponse(AnnotationCommentResponse):
    created_by: AvatarResearchCreatorResponse


class AvatarAnnotationThreadSummaryResponse(AnnotationThreadSummaryResponse):
    created_by: AvatarResearchCreatorResponse
    resolved_by: AvatarResearchCreatorResponse | None
    comments: Sequence[AvatarAnnotationCommentResponse]


class AvatarAnnotationThreadListResponse(BaseModel):
    items: list[AvatarAnnotationThreadSummaryResponse]
    next_cursor: str | None = None


__all__ = [
    "AvatarAnnotationCommentResponse",
    "AvatarAnnotationThreadListResponse",
    "AvatarAnnotationThreadSummaryResponse",
    "AvatarResearchCreatorResponse",
]
