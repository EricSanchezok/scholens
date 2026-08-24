"""Bounded live-state plans for confirmed Research mutations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnnotationThreadDeletionState(BaseModel):
    """Small revision facts that invalidate a thread-deletion confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: UUID
    creator_id: int
    item_updated_at: datetime
    thread_updated_at: datetime
    comment_count: int = Field(ge=0)
    comment_revision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AnnotationThreadDeletionPlan:
    state: AnnotationThreadDeletionState


__all__ = ["AnnotationThreadDeletionPlan", "AnnotationThreadDeletionState"]
