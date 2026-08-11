"""Sanitized conversation trace contracts shared by streams and snapshots."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationActivity(BaseModel):
    """One sanitized, user-inspectable tool lifecycle entry."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["activity"] = "activity"
    id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    category: Literal["search", "read", "workspace_action", "connector"]
    state: Literal["running", "succeeded", "failed"]
    subject: str | None = Field(default=None, max_length=240)
    connector_name: str | None = Field(default=None, max_length=80)
    source_count: int | None = Field(default=None, ge=0)
    artifact_count: int | None = Field(default=None, ge=0)


class ConversationCitationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_count: int = Field(ge=0)
    annotation_count: int = Field(ge=0)
    rejected_source_count: int = Field(ge=0)


class ConversationProgressEntry(BaseModel):
    """One safe, user-visible progress statement emitted before tool work."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["progress"] = "progress"
    id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=4_000)


ConversationTraceEntry = Annotated[
    ConversationProgressEntry | ConversationActivity,
    Field(discriminator="kind"),
]


class ConversationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[ConversationTraceEntry] = Field(default_factory=list)
    citation_summary: ConversationCitationSummary | None = None
