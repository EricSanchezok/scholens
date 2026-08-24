"""Validated contracts consumed from the Jobs service."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from scholens_job_contracts import (
    MAX_JOBS_CALLBACK_BODY_BYTES,
    MAX_ZOTERO_CALLBACK_BYTES,
    UNICODE_REPLACEMENT_CHARACTER,
    UNICODE_REPLACEMENT_WARNING_CODE,
    require_pdf_callback_content_size,
)

from app.shared.domain import JsonValue
from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.papers.application.contracts.extraction import PaperMetadataExtraction
from app.modules.papers.application.contracts.extraction import DataTableRow
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_serializer,
    field_validator,
    model_validator,
)


class JobClaimResponse(BaseModel):
    claimed: bool


class JobIntegrationCredentialResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: SecretStr
    credential_revision: UUID

    @field_serializer("credential", when_used="json")
    def serialize_credential(self, credential: SecretStr) -> str:
        return credential.get_secret_value()


class ZoteroJobCredentialResponse(JobIntegrationCredentialResponse):
    zotero_user_id: str = Field(min_length=1, max_length=64)


class ActionableJobFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    retryable: bool
    required_integration: Literal["mineru"] | None = None


class JobProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    progress_code: Literal[
        "downloading",
        "parsing",
        "extracting_metadata",
        "indexing",
        "finalizing",
        "fetching_library",
        "syncing_annotations",
        "importing_papers",
    ]


class JobCallbackIdentity(BaseModel):
    task_id: UUID


class PdfPostprocessCallback(JobCallbackIdentity):
    model_config = ConfigDict(extra="forbid")

    embedding: list[float] | None = Field(
        default=None,
        min_length=384,
        max_length=384,
    )
    embedding_model_revision: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    embedding_source_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_embedding_projection(self) -> PdfPostprocessCallback:
        values = (
            self.embedding,
            self.embedding_model_revision,
            self.embedding_source_digest,
        )
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("embedding projection fields must be supplied together")
        if self.embedding is not None and not all(
            math.isfinite(value) for value in self.embedding
        ):
            raise ValueError("embedding values must be finite")
        return self


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


class IntegrationUseEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mineru", "zotero"]
    credential_revision: UUID
    outcome: Literal["verified", "invalid", "failed"]
    error_code: str | None = Field(default=None, min_length=1, max_length=128)


ZoteroKey = Annotated[str, Field(pattern=r"^[A-Z0-9]{8}$")]
BoundedZoteroText = Annotated[str, Field(max_length=2_000)]
MAX_ZOTERO_ANNOTATIONS_BYTES = 2 * 1024 * 1024
_ZOTERO_KEY = re.compile(r"^[A-Z0-9]{8}$")


class ZoteroWorkerMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: ZoteroKey
    title: BoundedZoteroText
    authors: list[Annotated[str, Field(max_length=512)]] = Field(
        default_factory=list,
        max_length=100,
    )
    abstract: str | None = Field(default=None, max_length=200_000)
    publish_date: str | None = Field(default=None, max_length=128)
    doi: str | None = Field(default=None, max_length=512)
    tags: list[Annotated[str, Field(max_length=512)]] = Field(
        default_factory=list,
        max_length=100,
    )
    date_added: str | None = Field(default=None, max_length=64)
    item_type: Literal["journalArticle", "conferencePaper", "preprint"]
    venue: str | None = Field(default=None, max_length=2_000)
    collection_keys: list[ZoteroKey] = Field(default_factory=list, max_length=100)
    has_pdf_attachment: bool = False
    has_resolvable_source: bool = False
    has_metadata: bool = True
    version: int | None = None


class ZoteroWorkerAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: ZoteroKey
    import_source: Literal["pdf_attachment", "url"]
    attachment_key: ZoteroKey | None = None
    source_url: str | None = Field(default=None, max_length=2_048)
    annotations_json: str = Field(max_length=MAX_ZOTERO_ANNOTATIONS_BYTES)
    version: int | None = None

    @field_validator("annotations_json")
    @classmethod
    def validate_annotations(cls, value: str) -> str:
        return _validate_annotations_json(value)


class ZoteroWorkerImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: ZoteroKey
    version: int | None = None
    status: Literal["ready", "failed"]
    title: str | None = Field(default=None, max_length=2_000)
    error_code: str | None = Field(default=None, max_length=128)
    s3_object_key: str | None = Field(default=None, max_length=512)
    metadata: ZoteroWorkerMetadata | None = None
    attachment: ZoteroWorkerAttachment | None = None
    page_dimensions: list[tuple[int, float, float]] = Field(
        default_factory=list,
        max_length=10_000,
    )

    @model_validator(mode="after")
    def validate_state(self) -> "ZoteroWorkerImportItem":
        if self.status == "ready" and (
            not self.s3_object_key or self.metadata is None or self.attachment is None
        ):
            raise ValueError("ready Zotero import item is incomplete")
        if self.status == "failed" and not self.error_code:
            raise ValueError("failed Zotero import item requires an error code")
        if self.metadata is not None and self.metadata.item_key != self.item_key:
            raise ValueError("Zotero metadata item key does not match")
        if self.attachment is not None and self.attachment.item_key != self.item_key:
            raise ValueError("Zotero attachment item key does not match")
        return self


class ZoteroWorkerSyncUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: ZoteroKey
    attachment_key: ZoteroKey
    annotations_json: str = Field(max_length=MAX_ZOTERO_ANNOTATIONS_BYTES)

    @field_validator("annotations_json")
    @classmethod
    def validate_annotations(cls, value: str) -> str:
        return _validate_annotations_json(value)


class ZoteroWorkerFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: ZoteroKey
    error_code: str = Field(min_length=1, max_length=128)


class ZoteroImportWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    operation: Literal["import"]
    credential_revision: UUID
    credential_outcome: Literal["verified", "invalid", "failed"]
    error_code: str | None = Field(default=None, max_length=128)
    items: list[ZoteroWorkerImportItem] = Field(max_length=50)
    library_version: int | None = None

    @model_validator(mode="after")
    def validate_callback_size(self) -> "ZoteroImportWebhookData":
        _validate_zotero_staging_keys(self.task_id, self.items)
        if len(self.model_dump_json().encode()) > MAX_ZOTERO_CALLBACK_BYTES:
            raise ValueError("Zotero callback payload is too large")
        return self


class ZoteroSyncWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    operation: Literal["sync"]
    credential_revision: UUID
    credential_outcome: Literal["verified", "invalid", "failed"]
    error_code: str | None = Field(default=None, max_length=128)
    updates: list[ZoteroWorkerSyncUpdate] = Field(default_factory=list, max_length=500)
    failures: list[ZoteroWorkerFailure] = Field(default_factory=list, max_length=500)
    auto_imports: list[ZoteroWorkerImportItem] = Field(
        default_factory=list, max_length=50
    )
    library_version: int | None = None
    auto_import_base_version: int | None = None
    auto_import_base_start: int = Field(default=0, ge=0)
    auto_import_caught_up_version: int | None = None

    @model_validator(mode="after")
    def validate_callback_size(self) -> "ZoteroSyncWebhookData":
        _validate_zotero_staging_keys(self.task_id, self.auto_imports)
        if len(self.model_dump_json().encode()) > MAX_ZOTERO_CALLBACK_BYTES:
            raise ValueError("Zotero callback payload is too large")
        return self


def _validate_zotero_staging_keys(
    task_id: UUID,
    items: list[ZoteroWorkerImportItem],
) -> None:
    for item in items:
        if item.status != "ready":
            continue
        expected = f"zotero-imports/{task_id}/{item.item_key}.pdf"
        if item.s3_object_key != expected:
            raise ValueError("Zotero staging object key does not match callback")


def _validate_annotations_json(value: str) -> str:
    try:
        annotations = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Zotero annotations must be valid JSON") from exc
    if not isinstance(annotations, list) or len(annotations) > 10_000:
        raise ValueError("Zotero annotations exceed the supported item count")
    for annotation in annotations:
        if (
            not isinstance(annotation, dict)
            or _ZOTERO_KEY.fullmatch(str(annotation.get("key") or "")) is None
            or not isinstance(annotation.get("data"), dict)
        ):
            raise ValueError("Zotero annotation payload is invalid")
    return value


class PDFProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    job_id: str = Field(min_length=1, max_length=128)
    raw_content: str | None = None
    page_offset_map: dict[int, list[int]] | None = None
    page_count: int | None = Field(default=None, ge=1, le=10_000)
    metadata: PaperMetadataExtraction | None = None
    s3_object_key: str | None = Field(default=None, max_length=1_024)
    preview_s3_key: str | None = Field(default=None, max_length=1_024)
    parser_markdown_s3_key: str | None = Field(default=None, max_length=1_024)
    parser_archive_s3_key: str | None = Field(default=None, max_length=1_024)
    parser_backend: Literal["mineru", "pymupdf4llm", "markitdown"] | None = None
    parser_quality: Literal["full", "text_only"] | None = None
    parser_version: str | None = Field(default=None, max_length=160)
    parser_warning_code: str | None = Field(default=None, max_length=128)
    error: str | None = Field(default=None, max_length=128)
    duration: float | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def validate_uncoerced_parser_content(cls, value: object) -> object:
        if isinstance(value, dict):
            raw_content = value.get("raw_content")
            page_offset_map = value.get("page_offset_map")
            require_pdf_callback_content_size(
                raw_content=raw_content if isinstance(raw_content, str) else None,
                page_offset_map=(
                    page_offset_map if isinstance(page_offset_map, dict) else None
                ),
            )
        return value

    @model_validator(mode="after")
    def validate_result_state(self) -> "PDFProcessingResult":
        require_pdf_callback_content_size(
            raw_content=self.raw_content,
            page_offset_map=self.page_offset_map,
        )
        if self.duration is not None and not math.isfinite(self.duration):
            raise ValueError("PDF result duration must be finite")
        if self.success:
            if (
                not self.raw_content
                or not self.page_offset_map
                or self.parser_backend is None
                or self.parser_quality is None
                or not self.parser_version
            ):
                raise ValueError("successful PDF result is incomplete")
            if UNICODE_REPLACEMENT_CHARACTER in self.raw_content:
                # An older worker may still complete during a rolling deploy.
                # Preserve the original text, but never label it full-quality.
                self.parser_quality = "text_only"
                self.parser_warning_code = UNICODE_REPLACEMENT_WARNING_CODE
        elif not self.error:
            raise ValueError("failed PDF result requires an error code")
        if (
            self.page_count is not None
            and self.page_offset_map
            and max(self.page_offset_map) > self.page_count
        ):
            raise ValueError("page offsets exceed the physical PDF page count")
        return self


class PdfProcessingWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: Literal["completed", "failed"]
    result: PDFProcessingResult
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)
    integration_events: list[IntegrationUseEventPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_callback_size(self) -> "PdfProcessingWebhookData":
        if len(self.model_dump_json().encode()) > MAX_JOBS_CALLBACK_BODY_BYTES:
            raise ValueError("Jobs callback payload is too large")
        return self


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
    mineru_archive_s3_key: str | None = Field(default=None, max_length=1_024)
    mineru_archive_parser_revision: str | None = Field(default=None, max_length=160)


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
    integration_events: list[IntegrationUseEventPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "DocumentReflowWebhookData":
        if self.status == "completed" and self.result is None:
            raise ValueError("completed reflow job requires a result")
        if self.status == "failed" and not self.error:
            raise ValueError("failed reflow job requires an error code")
        return self
