"""Transport-neutral confirmation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.shared.domain import JsonValue

from pydantic import BaseModel, ConfigDict, Field


class ActionImpact(BaseModel):
    """Bounded, user-facing consequences of one proposed action."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1_000)
    consequences: list[str] = Field(default_factory=list, max_length=20)
    affected_resources: list[str] = Field(default_factory=list, max_length=100)


class ConfirmationChallenge(BaseModel):
    """A non-mutating response that an Agent must present before retrying."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["confirmation_required"] = "confirmation_required"
    confirmation_token: str = Field(min_length=32, max_length=256)
    expires_at: datetime
    impact: ActionImpact
    next_step: Literal["show_impact_to_user_then_retry_same_tool_with_token"] = (
        "show_impact_to_user_then_retry_same_tool_with_token"
    )


@dataclass(frozen=True, slots=True)
class ActionConfirmationRecord:
    actor_id: int
    credential_kind: str
    credential_reference: str | None
    action: str
    arguments_hash: str
    state_fingerprint: str
    consumed_at: datetime | None
    expires_at: datetime


class ActionConfirmationStore(Protocol):
    """Persistence boundary used by the confirmation application service."""

    def create(
        self,
        *,
        actor_id: int,
        credential_kind: str,
        credential_reference: str | None,
        action: str,
        arguments_hash: str,
        state_fingerprint: str,
        impact: JsonValue,
        token_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> None: ...

    def lock_by_token_hash(
        self, *, token_hash: str
    ) -> ActionConfirmationRecord | None: ...

    def mark_consumed(self, *, token_hash: str, now: datetime) -> None: ...

    def delete_expired(self, *, now: datetime) -> None: ...


__all__ = [
    "ActionConfirmationRecord",
    "ActionConfirmationStore",
    "ActionImpact",
    "ConfirmationChallenge",
]
