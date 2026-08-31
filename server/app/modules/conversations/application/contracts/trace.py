"""Sanitized conversation trace contracts shared by streams and snapshots."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    """Safe, additive provenance summary for one completed response.

    ``source_count`` intentionally remains the number of sources that are
    actually attached to answer spans.  ``available_source_count`` describes
    the wider source registry and must never be used to imply support.
    """

    # These three fields predate the status extension and remain required in
    # the public contract. Making them optional would be a response breaking
    # change even though the runtime could infer defaults.
    source_count: int = Field(ge=0)
    annotation_count: int = Field(ge=0)
    rejected_source_count: int = Field(ge=0)
    status: Literal["not_required", "complete", "partial", "unavailable", "pending"] = (
        "not_required"
    )
    grounding_status: Literal["not_evaluated", "verified", "mixed", "unverified"] = (
        "not_evaluated"
    )
    available_source_count: int = Field(default=0, ge=0)
    unlinked_source_count: int = Field(default=0, ge=0)
    dropped_annotation_count: int = Field(default=0, ge=0)
    unverified_claim_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def infer_legacy_summary(self) -> "ConversationCitationSummary":
        """Make pre-status persisted traces meaningful without a migration."""
        if self.available_source_count == 0 and self.source_count > 0:
            self.available_source_count = self.source_count
        if self.status == "not_required" and self.source_count > 0:
            self.status = "complete" if self.annotation_count > 0 else "unavailable"
        return self


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
