"""Versioned, replayable conversation stream contract.

The v2 envelope is intentionally small.  Payloads remain product-safe and
carry the ordering metadata required by a reconnecting browser reducer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.shared.domain import JsonValue
from pydantic import BaseModel, ConfigDict, Field

V2Phase = Literal[
    "queued",
    "thinking",
    "tool",
    "synthesizing",
    "finalizing",
    "completed",
    "failed",
    "canceled",
]


class ConversationStreamV2Event(BaseModel):
    """One ordered event in the v2 conversation stream."""

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[2] = 2
    event: str = Field(min_length=1, max_length=80)
    response_id: UUID
    seq: int = Field(ge=1)
    emitted_at: datetime
    data: dict[str, JsonValue] = Field(default_factory=dict)


class ConversationStreamV2Accepted(BaseModel):
    """The 202 body shared by the v2 direct and detachable paths."""

    conversation_id: UUID
    turn_id: UUID
    response_id: UUID


__all__ = [
    "ConversationStreamV2Accepted",
    "ConversationStreamV2Event",
    "V2Phase",
]
