"""Validated contracts consumed from the Jobs service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.shared.domain import JsonValue
from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.papers.application.contracts.extraction import PaperMetadataExtraction
from app.modules.papers.application.contracts.extraction import DataTableRow
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JobClaimResponse(BaseModel):
    claimed: bool


class JobProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    progress_code: Literal[
        "downloading",
        "parsing",
        "extracting_metadata",
        "indexing",
        "finalizing",
    ]


class JobCallbackIdentity(BaseModel):
    task_id: UUID


class JobFailureCallback(JobCallbackIdentity):
    error_code: str = Field(min_length=1, max_length=128)


class StorageDeleteCallback(JobCallbackIdentity):
    deleted_count: int


class TokenUsageEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=160)
    operation_id: str = Field(min_length=1, max_length=128)
    feature: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    ai_profile: str = Field(min_length=1, max_length=32)
    thinking: Literal["disabled", "enabled"]
    thinking_effort: Literal["none", "low", "medium", "high", "max"]
    profile_revision: str = Field(min_length=1, max_length=64)
    provider_request_id: str | None = Field(default=None, max_length=160)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cache_hit_tokens: int = Field(default=0, ge=0)
    cache_miss_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(ge=0)
    status: str = Field(default="settled", pattern="^(settled|unknown)$")


class PDFProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    job_id: str
    raw_content: str | None = None
    page_offset_map: dict[int, list[int]] | None = None
    metadata: PaperMetadataExtraction | None = None
    s3_object_key: str | None = None
    preview_s3_key: str | None = None
    parser_markdown_s3_key: str | None = None
    parser_archive_s3_key: str | None = None
    parser_backend: Literal["mineru", "pymupdf4llm", "markitdown"] | None = None
    parser_quality: Literal["full", "text_only"] | None = None
    parser_version: str | None = None
    parser_warning_code: str | None = None
    error: str | None = None
    duration: float | None = None

    @model_validator(mode="after")
    def validate_result_state(self) -> "PDFProcessingResult":
        if self.success:
            if (
                not self.raw_content
                or not self.page_offset_map
                or self.parser_backend is None
                or self.parser_quality is None
                or not self.parser_version
            ):
                raise ValueError("successful PDF result is incomplete")
        elif not self.error:
            raise ValueError("failed PDF result requires an error code")
        return self


class PdfProcessingWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: Literal["completed", "failed"]
    result: PDFProcessingResult
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: UUID
    operation: str
    document_id: UUID | None
    project_id: UUID | None
    status: str
    progress_code: str | None
    error_code: str | None
    result: dict[str, JsonValue] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class CreateAudioOverviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    additional_instructions: str | None = Field(default=None, max_length=10_000)
    length: Literal["short", "medium", "long"] = "medium"


class CreateJobResponse(BaseModel):
    job: JobResponse


class CreateDataTableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=240)
    columns: list[str] = Field(min_length=1, max_length=50)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, columns: list[str]) -> list[str]:
        normalized = [column.strip() for column in columns]
        if any(not column or len(column) > 200 for column in normalized):
            raise ValueError("columns must contain between 1 and 200 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("columns must be unique")
        return normalized


class JobListResponse(BaseModel):
    items: list[JobResponse]
    next_cursor: str | None = None


class AudioSourceDocumentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    canonical_s3_key: str


class AudioOverviewTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: UUID
    scope_type: Literal["document", "project"]
    scope_id: UUID
    documents: list[AudioSourceDocumentPayload] = Field(min_length=1, max_length=100)
    length: Literal["short", "medium", "long"]
    additional_instructions: str | None = Field(default=None, max_length=10_000)


class AudioOverviewResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: UUID
    title: str
    transcript: str = Field(min_length=1)
    citations: list[ResponseCitation]
    s3_object_key: str = Field(min_length=1, max_length=1024)
    voice_id: str = Field(min_length=1, max_length=160)
    model_version: str = Field(min_length=1, max_length=160)


class AudioOverviewWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: Literal["completed", "failed"]
    result: AudioOverviewResultPayload | None = None
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "AudioOverviewWebhookData":
        if self.status == "completed" and self.result is None:
            raise ValueError("completed audio job requires a result")
        if self.status == "failed" and not self.error:
            raise ValueError("failed audio job requires an error code")
        return self


class DataTableSourceDocumentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    raw_content: str


class DataTableTaskTablePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=1, max_length=50)
    papers: list[DataTableSourceDocumentPayload] = Field(min_length=1, max_length=500)


class DataTableTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: UUID
    title: str | None = Field(default=None, max_length=240)
    table: DataTableTaskTablePayload


class ResearchDataTableResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: UUID
    title: str | None = Field(default=None, max_length=240)
    columns: list[str]
    rows: list[DataTableRow]
    row_failures: list[UUID]


class DataTableWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: Literal["completed", "failed"]
    result: ResearchDataTableResultPayload | None = None
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "DataTableWebhookData":
        if self.status == "completed" and self.result is None:
            raise ValueError("completed data-table job requires a result")
        if self.status == "failed" and not self.error:
            raise ValueError("failed data-table job requires an error code")
        return self


ReflowBlockKind = Literal[
    "eyebrow",
    "title",
    "authors",
    "affiliations",
    "abstract",
    "keywords",
    "heading",
    "paragraph",
    "list",
    "quote",
    "equation",
    "table",
    "figure",
    "caption",
    "code",
    "footnote",
    "references",
]

ReflowPresentationStatus = Literal["verbatim", "repaired", "degraded"]
ReflowAssetKind = Literal["raster", "vector", "composite", "table_preview"]


class ReflowSourceRectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class DocumentReflowTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    title: str = Field(min_length=1, max_length=1_000)
    pdf_s3_key: str = Field(min_length=1, max_length=1_024)


class ReflowSourceSpanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    source_rect: ReflowSourceRectPayload
    source_text: str = Field(min_length=1)


class DocumentReflowBlockPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    index: int = Field(ge=0)
    kind: ReflowBlockKind
    render_markdown: str = Field(min_length=1)
    group_id: str | None = Field(default=None, min_length=1, max_length=128)
    heading_level: int | None = Field(default=None, ge=1, le=6)
    source_spans: list[ReflowSourceSpanPayload] = Field(min_length=1)
    presentation_status: ReflowPresentationStatus
    asset_id: str | None = Field(default=None, min_length=1, max_length=128)


class DocumentReflowAssetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    object_key: str = Field(min_length=1, max_length=1_024)
    kind: ReflowAssetKind
    content_type: str = Field(min_length=1, max_length=128)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    page_number: int = Field(ge=1)
    source_rect: ReflowSourceRectPayload
    checksum: str = Field(pattern="^[0-9a-f]{64}$")


class DocumentReflowResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    source_hash: str = Field(pattern="^[0-9a-f]{64}$")
    pipeline_revision: str = Field(min_length=1, max_length=64)
    parser_revision: str = Field(min_length=1, max_length=64)
    blocks: list[DocumentReflowBlockPayload] = Field(min_length=1)
    assets: list[DocumentReflowAssetPayload] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=1_000)


class DocumentReflowWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: Literal["completed", "failed"]
    result: DocumentReflowResultPayload | None = None
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "DocumentReflowWebhookData":
        if self.status == "completed" and self.result is None:
            raise ValueError("completed reflow job requires a result")
        if self.status == "failed" and not self.error:
            raise ValueError("failed reflow job requires an error code")
        return self
