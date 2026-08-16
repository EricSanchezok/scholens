"""Public, secret-free contracts for the Zotero integration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ZoteroIntent = Literal["manage", "import"]
ZoteroConnectionState = Literal["disconnected", "connected", "invalid"]
ZoteroAutomaticState = Literal["active", "off", "paused"]
ZoteroImportState = Literal["available", "imported", "in_progress", "failed"]
ZoteroSourceAvailability = Literal["stored_pdf", "resolvable_source", "unavailable"]
ZoteroOperationStatus = Literal[
    "queued", "running", "partial", "succeeded", "failed", "cancelled"
]
ZoteroOperationKind = Literal["import", "sync"]
ZoteroOperationProgress = Literal[
    "queued",
    "fetching_library",
    "syncing_annotations",
    "importing_papers",
]


class ZoteroOAuthAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    return_path: str = Field(min_length=1, max_length=2_048)
    intent: ZoteroIntent = "manage"

    @field_validator("return_path")
    @classmethod
    def validate_return_path(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
        ):
            raise ValueError("return_path must be a local absolute path")
        return value


class ZoteroConnectResponse(BaseModel):
    auth_url: str


class ZoteroConnectionStatus(BaseModel):
    connection_state: ZoteroConnectionState
    connected_at: datetime | None = None
    last_successful_sync_at: datetime | None = None
    automatic_sync_eligible: bool = False
    automatic_annotation_sync: ZoteroAutomaticState
    auto_import_enabled: bool = False
    auto_import_state: ZoteroAutomaticState = "off"
    last_error_code: str | None = None
    active_operation_id: UUID | None = None
    active_operation_kind: ZoteroOperationKind | None = None


class ZoteroSyncPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_import_enabled: bool


class ZoteroImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_keys: list[str] = Field(..., min_length=1, max_length=50)

    @field_validator("item_keys")
    @classmethod
    def validate_item_keys(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 64 for value in normalized):
            raise ValueError("item_keys must contain non-empty Zotero keys")
        if len(set(normalized)) != len(normalized):
            raise ValueError("item_keys must be unique")
        return normalized


class ZoteroImportItemResult(BaseModel):
    zotero_item_key: str
    document_id: str | None = None
    upload_job_id: str | None = None
    import_source: str | None = None
    title: str | None = None


class ZoteroImportError(BaseModel):
    zotero_item_key: str
    error: str


class ZoteroOperationItem(BaseModel):
    zotero_item_key: str
    status: Literal["queued", "running", "accepted", "failed", "cancelled"]
    title: str | None = None
    document_id: UUID | None = None
    ingestion_job_id: UUID | None = None
    error_code: str | None = None


class ZoteroOperationCounts(BaseModel):
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)


class ZoteroOperation(BaseModel):
    id: UUID
    kind: ZoteroOperationKind
    status: ZoteroOperationStatus
    progress_code: ZoteroOperationProgress | None = None
    counts: ZoteroOperationCounts
    items: list[ZoteroOperationItem] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ZoteroCollection(BaseModel):
    key: str
    name: str


class ZoteroCollectionPage(BaseModel):
    items: list[ZoteroCollection]
    next_cursor: str | None = None
    previous_cursor: str | None = None
    total_count: int


class ZoteroLibraryItem(BaseModel):
    zotero_item_key: str
    title: str
    authors: list[str]
    date: str | None = None
    item_type: str
    venue: str | None = None
    date_added: str | None = None
    tags: list[str] = Field(default_factory=list)
    collection_keys: list[str] = Field(default_factory=list)
    import_state: ZoteroImportState
    source_availability: ZoteroSourceAvailability


class ZoteroLibraryPage(BaseModel):
    items: list[ZoteroLibraryItem]
    next_cursor: str | None = None
    previous_cursor: str | None = None
    total_count: int
    remaining_slots: int
    max_batch_size: int = 50


class ZoteroSyncResponse(BaseModel):
    synced_papers_count: int
    new_annotations_count: int


# Internal import-application result retained between the Zotero batch and the
# standard paper-ingestion lifecycle. It is never returned by the public POST.
class ZoteroImportResponse(BaseModel):
    imported: list[ZoteroImportItemResult]
    imported_count: int
    imported_via_url: int
    skipped_already_imported: int
    skipped_item_keys: list[str] = Field(default_factory=list)
    errors: list[ZoteroImportError]
