from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from app.shared.domain import JsonValue
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchAudienceType,
    ResearchItemKind,
)
from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationMethod,
)
from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.research.application.positions import ResearchPosition
from pydantic import BaseModel, ConfigDict, Field, model_validator


UPDATE_ANNOTATION_THREAD_JSON_SCHEMA_EXTRA: dict[str, Any] = {
    "oneOf": [
        {
            "required": ["color"],
            "properties": {
                "color": {
                    "description": "Replacement highlight color.",
                    "not": {"type": "null"},
                },
                "status": {
                    "description": "Must be null when color is changed.",
                    "type": "null",
                },
            },
        },
        {
            "required": ["status"],
            "properties": {
                "color": {
                    "description": "Must be null when status is changed.",
                    "type": "null",
                },
                "status": {
                    "description": "Replacement discussion status.",
                    "not": {"type": "null"},
                },
            },
        },
    ]
}


class ResearchCreatorResponse(BaseModel):
    id: int | None
    display_name: str | None


class AnnotationCommentResponse(BaseModel):
    id: UUID
    thread_id: UUID
    content: str
    role: str
    created_by: ResearchCreatorResponse
    created_at: datetime
    updated_at: datetime
    can_edit: bool
    can_delete: bool


class PersonalResearchAudience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["personal"] = Field(
        default="personal",
        description="Keep the research item visible only to its creator.",
    )


class DocumentResearchAudience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["document"] = Field(
        default="document",
        description="Share the research item through one authorized document scope.",
    )
    document_id: UUID = Field(
        description="Immutable Scholens document UUID defining the audience."
    )


class ProjectResearchAudience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["project"] = Field(
        default="project",
        description="Share the research item with current members of one Project.",
    )
    project_id: UUID = Field(
        description="Immutable Scholens Project UUID defining the audience."
    )


ResearchAudience = Annotated[
    PersonalResearchAudience | DocumentResearchAudience | ProjectResearchAudience,
    Field(discriminator="kind"),
]
AnnotationAudience = Annotated[
    PersonalResearchAudience | ProjectResearchAudience,
    Field(discriminator="kind"),
]


class AnnotationThreadCapabilities(BaseModel):
    reply: bool
    recolor: bool
    resolve: bool
    reopen: bool
    delete: bool


class AnnotationThreadContent(BaseModel):
    quote_text: str
    position: ResearchPosition | None
    color: AnnotationColor
    role: str
    mode: AnnotationThreadMode
    comment_count: int = Field(ge=0)
    last_activity_at: datetime
    status: AnnotationThreadStatus
    resolved_by: ResearchCreatorResponse | None
    resolved_at: datetime | None
    capabilities: AnnotationThreadCapabilities
    comments: list[AnnotationCommentResponse]


class AnnotationThreadSummaryResponse(BaseModel):
    id: UUID
    audience: AnnotationAudience
    target_document_id: UUID
    created_by: ResearchCreatorResponse
    created_at: datetime
    quote_text: str
    position: ResearchPosition | None
    color: AnnotationColor
    role: str
    mode: AnnotationThreadMode
    comment_count: int = Field(ge=0)
    last_activity_at: datetime
    status: AnnotationThreadStatus
    resolved_by: ResearchCreatorResponse | None
    resolved_at: datetime | None
    capabilities: AnnotationThreadCapabilities
    comments: Sequence[AnnotationCommentResponse]


class AnnotationThreadListResponse(BaseModel):
    items: list[AnnotationThreadSummaryResponse]
    next_cursor: str | None = None


class CitationSnapshot(BaseModel):
    """Immutable, validated citation card emitted by the evidence pipeline."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["citation"]
    document_id: str = Field(min_length=1, max_length=100)
    preferred_style: str = Field(min_length=1, max_length=100)
    style_display: str = Field(min_length=1, max_length=200)
    data: CitationData
    method: CitationMethod
    missing_fields: list[str] = Field(default_factory=list, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)


class CitationContent(BaseModel):
    snapshot: CitationSnapshot


class AudioOverviewContent(BaseModel):
    title: str | None
    transcript: str
    citations: list[ResponseCitation]
    audio_url: str
    voice_id: str
    model_version: str


class DataTableContent(BaseModel):
    title: str | None
    columns: list[str]
    rows: list[dict[str, JsonValue]]
    citations: list[dict[str, JsonValue]]
    row_failures: list[str]


class ResearchItemCapabilities(BaseModel):
    edit: bool
    delete: bool


class ResearchItemResponse(BaseModel):
    id: UUID
    kind: ResearchItemKind
    audience: ResearchAudience
    target_document_id: UUID | None
    created_by: ResearchCreatorResponse
    created_at: datetime
    updated_at: datetime
    capabilities: ResearchItemCapabilities
    annotation_thread: AnnotationThreadContent | None = None
    citation: CitationContent | None = None
    audio_overview: AudioOverviewContent | None = None
    data_table: DataTableContent | None = None

    @model_validator(mode="after")
    def validate_content(self) -> ResearchItemResponse:
        populated = sum(
            value is not None
            for value in (
                self.annotation_thread,
                self.citation,
                self.audio_overview,
                self.data_table,
            )
        )
        if populated != 1:
            raise ValueError("research item must contain exactly one typed payload")
        return self


class ResearchItemListResponse(BaseModel):
    items: list[ResearchItemResponse]
    next_cursor: str | None = None


class ResearchOutputCreatorSummary(BaseModel):
    """Bounded creator identity for a catalog row."""

    model_config = ConfigDict(extra="forbid")

    id: int | None
    display_name: str | None = Field(default=None, max_length=320)


class ResearchOutputSourceSummary(BaseModel):
    """Stable audience source without storage or delivery credentials."""

    model_config = ConfigDict(extra="forbid")

    audience_type: ResearchAudienceType
    audience_id: UUID | None
    title: str = Field(min_length=1, max_length=240)


class ResearchOutputSummary(BaseModel):
    """Bounded catalog projection; complete output content is fetched separately."""

    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    kind: ResearchItemKind
    audience: ResearchAudience
    target_document_id: UUID | None
    title: str = Field(min_length=1, max_length=240)
    excerpt: str = Field(max_length=1_200)
    creator: ResearchOutputCreatorSummary
    created_at: datetime
    updated_at: datetime
    source: ResearchOutputSourceSummary
    resource_uri: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^scholens://(?:annotation-threads|research-outputs)/",
    )


class ResearchOutputSummaryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ResearchOutputSummary] = Field(max_length=25)
    next_cursor: str | None = Field(default=None, max_length=2_048)
    previous_cursor: str | None = Field(default=None, max_length=2_048)
    total_count: int = Field(ge=0)


class CreateAnnotationThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    quote_text: str = Field(min_length=1, max_length=100_000)
    position: ResearchPosition
    color: AnnotationColor = AnnotationColor.YELLOW
    audience: AnnotationAudience = Field(default_factory=PersonalResearchAudience)
    initial_comment: str | None = Field(default=None, min_length=1, max_length=100_000)


class UpdateAnnotationThreadRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra=UPDATE_ANNOTATION_THREAD_JSON_SCHEMA_EXTRA,
    )

    color: AnnotationColor | None = None
    status: AnnotationThreadStatus | None = None

    @model_validator(mode="after")
    def require_exactly_one_change(self) -> "UpdateAnnotationThreadRequest":
        if (self.color is None) == (self.status is None):
            raise ValueError("exactly one of color or status is required")
        return self


class CreateAnnotationCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=100_000)


class UpdateAnnotationCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=100_000)


class DeleteResearchItemResponse(BaseModel):
    deleted: Literal[True] = True
