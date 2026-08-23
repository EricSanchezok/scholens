import uuid
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.shared.domain import JsonValue
from app.shared.domain.enums import ReasoningLevel
from app.modules.conversations.application.contracts.contexts import TurnContext
from app.modules.conversations.application.contracts.conversations import (
    ConversationTurnResponse,
)
from app.modules.conversations.application.contracts.trace import (
    ConversationActivity,
)
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class ConversationStreamStartEvent(BaseModel):
    type: Literal["start"] = "start"
    conversation_id: uuid.UUID
    turn_id: uuid.UUID
    response_id: uuid.UUID
    variant_index: int = Field(ge=1)
    generation_kind: Literal["initial", "retry", "branch"]


class ConversationStreamActivityEvent(BaseModel):
    type: Literal["activity"] = "activity"
    response_id: uuid.UUID
    activity: ConversationActivity


class ConversationAssistantItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    phase: Literal["progress", "final"]
    content: str = Field(min_length=1, max_length=200_000)


class ConversationStreamAssistantItemStartEvent(BaseModel):
    type: Literal["assistant_item_start"] = "assistant_item_start"
    response_id: uuid.UUID
    item_id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)


class ConversationStreamAssistantItemDeltaEvent(BaseModel):
    type: Literal["assistant_item_delta"] = "assistant_item_delta"
    response_id: uuid.UUID
    item_id: str = Field(min_length=1, max_length=200)
    delta: str


class ConversationStreamAssistantItemDiscardEvent(BaseModel):
    type: Literal["assistant_item_discard"] = "assistant_item_discard"
    response_id: uuid.UUID
    item_id: str = Field(min_length=1, max_length=200)


class ConversationStreamAssistantItemCompleteEvent(BaseModel):
    type: Literal["assistant_item_complete"] = "assistant_item_complete"
    response_id: uuid.UUID
    item: ConversationAssistantItem


class ConversationStreamReferencesEvent(BaseModel):
    type: Literal["references"] = "references"
    response_id: uuid.UUID
    references: dict[str, JsonValue]


class ConversationStreamResponseReadyEvent(BaseModel):
    type: Literal["response_ready"] = "response_ready"
    turn: ConversationTurnResponse


class ConversationStreamSuggestionsEvent(BaseModel):
    type: Literal["suggestions"] = "suggestions"
    turn_id: uuid.UUID
    response_id: uuid.UUID
    suggestions: list[str] = Field(min_length=3, max_length=3)


class ConversationStreamCompleteEvent(BaseModel):
    type: Literal["complete"] = "complete"
    turn_id: uuid.UUID
    response_id: uuid.UUID


class ConversationStreamCancelledEvent(BaseModel):
    type: Literal["cancelled"] = "cancelled"
    turn_id: uuid.UUID
    response_id: uuid.UUID


class ConversationStreamErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    response_id: uuid.UUID
    error: dict[str, JsonValue]


ConversationLegacyStreamEvent = Annotated[
    ConversationStreamStartEvent
    | ConversationStreamActivityEvent
    | ConversationStreamAssistantItemStartEvent
    | ConversationStreamAssistantItemDeltaEvent
    | ConversationStreamAssistantItemDiscardEvent
    | ConversationStreamAssistantItemCompleteEvent
    | ConversationStreamReferencesEvent
    | ConversationStreamResponseReadyEvent
    | ConversationStreamSuggestionsEvent
    | ConversationStreamCompleteEvent
    | ConversationStreamErrorEvent,
    Field(discriminator="type"),
]

ConversationStreamEvent = Annotated[
    ConversationStreamStartEvent
    | ConversationStreamActivityEvent
    | ConversationStreamAssistantItemStartEvent
    | ConversationStreamAssistantItemDeltaEvent
    | ConversationStreamAssistantItemDiscardEvent
    | ConversationStreamAssistantItemCompleteEvent
    | ConversationStreamReferencesEvent
    | ConversationStreamResponseReadyEvent
    | ConversationStreamSuggestionsEvent
    | ConversationStreamCompleteEvent
    | ConversationStreamCancelledEvent
    | ConversationStreamErrorEvent,
    Field(discriminator="type"),
]


class ConversationStreamEventSchema(RootModel[ConversationLegacyStreamEvent]):
    """Compatible schema for the existing inline SSE response."""


class ConversationSubscriptionEventSchema(RootModel[ConversationStreamEvent]):
    """Schema for detachable response subscriptions, including cancellation."""


class ConversationTurnCreateRequest(BaseModel):
    """Create one user turn and its initial generated response."""

    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    response_id: uuid.UUID
    user_query: str = Field(min_length=1, max_length=20_000)
    locale: Literal["en", "zh-CN"]
    time_zone: str = Field(min_length=1, max_length=100)
    contexts: list[TurnContext] = Field(default_factory=list, max_length=50)
    reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("time_zone must be a valid IANA time zone") from exc
        return value


class ConversationTurnBranchCreateRequest(BaseModel):
    """Create an edited sibling branch without mutating the source turn."""

    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    response_id: uuid.UUID
    user_query: str = Field(min_length=1, max_length=20_000)


class ConversationResponseCreateRequest(BaseModel):
    """Generate another response variant for the latest conversation turn."""

    model_config = ConfigDict(extra="forbid")

    response_id: uuid.UUID


class ConversationResponseSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: uuid.UUID
