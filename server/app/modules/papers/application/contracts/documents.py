from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from app.shared.domain import JsonValue
from app.shared.domain.enums import (
    DocumentProcessingStatus,
    PaperStatus,
    ResearchAudienceType,
)
from app.modules.papers.application.contracts.extraction import ResponseCitation
from app.modules.research.application.contracts import ResearchItemResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator


class LibraryPaperSort(StrEnum):
    ADDED_DESC = "added_desc"
    ADDED_ASC = "added_asc"
    PUBLISHED_DESC = "published_desc"
    PUBLISHED_ASC = "published_asc"
    TITLE_ASC = "title_asc"


class LibraryOutputSort(StrEnum):
    UPDATED_DESC = "updated_desc"
    UPDATED_ASC = "updated_asc"
    TITLE_ASC = "title_asc"
    TITLE_DESC = "title_desc"


class DocumentUpdate(BaseModel):
    """Validated canonical metadata written by trusted ingestion workflows."""

    model_config = ConfigDict(extra="forbid")

    preview_s3_key: str | None = None
    authors: list[str] | None = None
    title: str | None = None
    abstract: str | None = None
    institutions: list[str] | None = None
    keywords: list[str] | None = None
    summary: str | None = None
    summary_citations: list[ResponseCitation] | None = None
    starter_questions: list[str] | None = None
    publish_date: datetime | str | None = None
    raw_content: str | None = None
    parser_markdown_s3_key: str | None = None
    parser_archive_s3_key: str | None = None
    parser_backend: str | None = None
    parser_quality: str | None = None
    parser_version: str | None = None
    parser_warning_code: str | None = None
    processing_status: str | None = None
    processing_job_id: UUID | None = None
    gc_after: datetime | None = None
    page_offset_map: dict[int, list[int]] | None = None
    doi: str | None = None
    journal: str | None = None
    publisher: str | None = None
    attempted_metadata_at: datetime | None = None
    field_provenance: dict[str, JsonValue] | None = None


class DocumentMetadataOverrides(BaseModel):
    """The only canonical metadata fields a Library owner may override."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=1_000)
    authors: list[str] | None = Field(default=None, max_length=100)
    abstract: str | None = Field(default=None, max_length=100_000)
    institutions: list[str] | None = Field(default=None, max_length=100)
    doi: str | None = Field(default=None, max_length=500)
    journal: str | None = Field(default=None, max_length=1_000)
    publisher: str | None = Field(default=None, max_length=1_000)
    publish_date: datetime | None = None

    @field_validator("authors", "institutions")
    @classmethod
    def validate_list_values(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 500 for value in normalized):
            raise ValueError(
                "metadata list values must be between 1 and 500 characters"
            )
        return normalized


class LibraryPaperUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PaperStatus | None = None
    metadata_overrides: DocumentMetadataOverrides | None = None


class DocumentResponse(BaseModel):
    document_id: UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    title: str | None
    authors: list[str] | None
    abstract: str | None
    institutions: list[str] | None
    keywords: list[str] | None
    doi: str | None
    journal: str | None
    publisher: str | None
    publish_date: datetime | None
    summary: str | None
    summary_citations: list[ResponseCitation] | None
    starter_questions: list[str] | None
    processing_status: DocumentProcessingStatus
    parser_quality: str | None
    parser_warning_code: str | None
    created_at: datetime
    updated_at: datetime


class LibraryPaperTagResponse(BaseModel):
    id: UUID
    name: str
    color: str | None


class LibraryPaperResponse(BaseModel):
    library_entry_id: UUID
    user_id: int
    status: PaperStatus
    last_accessed_at: datetime
    metadata_overrides: DocumentMetadataOverrides
    is_public: bool
    preview_url: str | None
    tags: list[LibraryPaperTagResponse]
    document: DocumentResponse
    created_at: datetime
    updated_at: datetime


class LibraryPaperIngestionResponse(BaseModel):
    id: UUID
    display_name: str
    source_kind: Literal["upload", "doi", "arxiv", "url"]
    state: Literal["queued", "processing", "failed"]
    stage: Literal[
        "queued",
        "downloading",
        "parsing",
        "extracting_metadata",
        "indexing",
        "finalizing",
    ]
    project_id: UUID | None
    document_id: UUID | None
    error_code: str | None
    created_at: datetime


class LibraryPaperListPaperEntry(LibraryPaperResponse):
    entry_type: Literal["paper"] = "paper"


class LibraryPaperListIngestionEntry(BaseModel):
    entry_type: Literal["ingestion"] = "ingestion"
    ingestion: LibraryPaperIngestionResponse


LibraryPaperListEntry = Annotated[
    LibraryPaperListPaperEntry | LibraryPaperListIngestionEntry,
    Field(discriminator="entry_type"),
]


class LibraryPaperListResponse(BaseModel):
    items: list[LibraryPaperListEntry]
    next_cursor: str | None = None
    previous_cursor: str | None = None
    total_count: int = Field(ge=0)


class LibraryOutputSourceResponse(BaseModel):
    audience_type: ResearchAudienceType
    audience_id: UUID | None
    title: str


class LibraryOutputResponse(BaseModel):
    item: ResearchItemResponse
    title: str
    source: LibraryOutputSourceResponse


class LibraryOutputListResponse(BaseModel):
    items: list[LibraryOutputResponse]
    next_cursor: str | None = None
    previous_cursor: str | None = None
    total_count: int = Field(ge=0)


class LibrarySummaryResponse(BaseModel):
    paper_count: int = Field(ge=0)
    ingestion_count: int = Field(ge=0)
    attention_count: int = Field(ge=0)
    output_count: int = Field(ge=0)


class LibraryPaperRemovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[UUID] = Field(min_length=1, max_length=120)

    @field_validator("document_ids")
    @classmethod
    def unique_document_ids(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("document_ids must be unique")
        return values


class LibraryPaperRemovalResponse(BaseModel):
    removed_document_ids: list[UUID]


class LibraryPaperShareResponse(BaseModel):
    share_token: str
    is_public: bool


class PublicPaperOwnerResponse(BaseModel):
    id: int
    display_name: str


class PublicPaperResponse(BaseModel):
    document: DocumentResponse
    file_url: str
    owner: PublicPaperOwnerResponse


class CollectPublicPaperResponse(BaseModel):
    document_id: UUID
    library_entry_id: UUID
    already_exists: bool


class DocumentFileUrlResponse(BaseModel):
    file_url: str
    expires_in_seconds: int


class DocumentContentResponse(BaseModel):
    document_id: UUID
    title: str | None
    abstract: str | None
    content: str | None
