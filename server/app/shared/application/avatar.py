"""Protocol-neutral reference to an expiring shared profile avatar."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AvatarReference(BaseModel):
    """A versioned, short-lived URL safe to expose to an authorized caller."""

    model_config = ConfigDict(frozen=True)

    url: str
    version: UUID
    expires_at: datetime


__all__ = ["AvatarReference"]
