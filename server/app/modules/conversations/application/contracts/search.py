"""Public contracts for searching durable conversation history."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.conversations.application.contracts.conversations import (
    ConversationSummaryResponse,
)


class ConversationSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=1_000)
    limit: int = Field(default=30, ge=1, le=50)
    cursor: str | None = Field(default=None, max_length=1_024)


class ConversationSearchPosition(BaseModel):
    score: float
    updated_at: datetime
    conversation_id: UUID


class ConversationSearchQuery(BaseModel):
    query: str
    limit: int = Field(ge=1, le=50)
    position: ConversationSearchPosition | None = None


class ConversationSearchResult(BaseModel):
    conversation: ConversationSummaryResponse
    matched_field: Literal[
        "title",
        "scope",
        "user_query",
        "assistant_response",
    ]
    snippet: str | None = None


class ConversationSearchResponse(BaseModel):
    items: list[ConversationSearchResult]
    total: int
    next_cursor: str | None = None


class ConversationSearchPage(BaseModel):
    items: list[ConversationSearchResult]
    total: int
    next_position: ConversationSearchPosition | None = None
