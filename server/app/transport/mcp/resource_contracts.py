"""Typed public payloads for Scholens MCP resource reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from app.shared.domain import JsonValue

from app.modules.papers.application.contracts.documents import (
    DocumentResponse,
    LibraryPaperListIngestionEntry,
    LibraryPaperListPaperEntry,
    LibrarySummaryResponse,
)
from app.modules.projects.application.contracts import (
    ProjectCollaboratorListResponse,
    ProjectListResponse,
    ProjectPaperSummaryResponse,
    ProjectResponse,
)
from app.modules.research.application.contracts import (
    ResearchOutputSummary,
)
from app.tooling.reader_links import READER_URL_DESCRIPTION, READER_URL_MAX_LENGTH
from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator


class ResourceContinuation(BaseModel):
    """A concrete bounded tool call that recovers one part of a manifest."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    provides: str


class McpResourcePayload(BaseModel):
    """Base contract that rejects accidental private-field additions."""

    model_config = ConfigDict(extra="forbid")

    resource_uri: str
    continuations: list[ResourceContinuation] = Field(min_length=1)
    content_truncated: bool = False
    guidance: str = Field(default="", max_length=1_000)


class TruncatedResourcePayload(McpResourcePayload):
    """Small continuation envelope returned instead of an oversized manifest."""

    truncated: Literal[True] = True
    serialized_size_bytes: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    continuation_tool: str
    continuations: list["ResourceContinuation"] = Field(min_length=1)
    guidance: str


class LibraryPaperResourcePaperEntryModel(LibraryPaperListPaperEntry):
    model_config = ConfigDict(from_attributes=True)
    reader_url: str | None = Field(
        default=None,
        max_length=READER_URL_MAX_LENGTH,
        description=READER_URL_DESCRIPTION,
    )


class LibraryPaperResourceIngestionEntryModel(LibraryPaperListIngestionEntry):
    model_config = ConfigDict(from_attributes=True)
    reader_url: str | None = Field(
        default=None,
        max_length=READER_URL_MAX_LENGTH,
        description=READER_URL_DESCRIPTION,
    )


LibraryPaperResourceEntry = Annotated[
    LibraryPaperResourcePaperEntryModel | LibraryPaperResourceIngestionEntryModel,
    Field(discriminator="entry_type"),
]


_READER_URL_SCHEMA = {
    "anyOf": [
        {"maxLength": READER_URL_MAX_LENGTH, "type": "string"},
        {"type": "null"},
    ],
    "default": None,
    "description": READER_URL_DESCRIPTION,
    "title": "Reader Url",
}

_LIBRARY_PAPER_LIST_BASE_ENTRY = Annotated[
    LibraryPaperListPaperEntry | LibraryPaperListIngestionEntry,
    Field(discriminator="entry_type"),
]
_LIBRARY_PAPER_READER_URL_ITEM_SCHEMA = Annotated[
    SerializeAsAny[_LIBRARY_PAPER_LIST_BASE_ENTRY],
    Field(json_schema_extra={"properties": {"reader_url": _READER_URL_SCHEMA}}),
]


class LibraryPaperResourceList(BaseModel):
    items: list[_LIBRARY_PAPER_READER_URL_ITEM_SCHEMA]
    next_cursor: str | None = None
    previous_cursor: str | None = None
    total_count: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def preserve_reader_url_entries(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        raw_items = value.get("items")
        if not isinstance(raw_items, list):
            return value
        normalized = dict(value)
        normalized["items"] = [
            (
                LibraryPaperResourcePaperEntryModel.model_validate(item)
                if isinstance(item, dict) and item.get("entry_type") == "paper"
                else (
                    LibraryPaperResourceIngestionEntryModel.model_validate(item)
                    if isinstance(item, dict) and item.get("entry_type") == "ingestion"
                    else item
                )
            )
            for item in raw_items
        ]
        return normalized


class ProjectPaperResourceSummary(ProjectPaperSummaryResponse):
    model_config = ConfigDict(from_attributes=True)
    reader_url: str | None = Field(
        default=None,
        max_length=READER_URL_MAX_LENGTH,
        description=READER_URL_DESCRIPTION,
    )


class ProjectPaperResourceList(BaseModel):
    items: list[ProjectPaperResourceSummary]
    next_cursor: str | None = None
    previous_cursor: str | None = None
    total_count: int = Field(default=0, ge=0)


class ResearchOutputSummaryResource(ResearchOutputSummary):
    model_config = ConfigDict(from_attributes=True)
    reader_url: str | None = Field(
        default=None,
        max_length=READER_URL_MAX_LENGTH,
        description=READER_URL_DESCRIPTION,
    )


class ResearchOutputSummaryResourceList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ResearchOutputSummaryResource] = Field(max_length=25)
    next_cursor: str | None = Field(default=None, max_length=2_048)
    previous_cursor: str | None = Field(default=None, max_length=2_048)
    total_count: int = Field(ge=0)


class LibraryResourcePayload(McpResourcePayload):
    summary: LibrarySummaryResponse
    papers: LibraryPaperResourceList
    research_outputs: ResearchOutputSummaryResourceList


class ProjectIndexResourcePayload(McpResourcePayload):
    projects: ProjectListResponse


class ProjectResourcePayload(McpResourcePayload):
    project: ProjectResponse
    papers: ProjectPaperResourceList
    members: ProjectCollaboratorListResponse
    research_outputs: ResearchOutputSummaryResourceList


class PaperContentPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_line: int = Field(ge=1)
    end_line: int = Field(ge=0)
    total_lines: int = Field(ge=0)
    lines: list[str]
    truncated: bool


class PaperResourcePayload(McpResourcePayload):
    paper: DocumentResponse
    reader_url: str | None = Field(
        default=None,
        max_length=READER_URL_MAX_LENGTH,
        description=READER_URL_DESCRIPTION,
    )
    content_preview: PaperContentPreview
    projects: ProjectListResponse


class AnnotationThreadResourcePayload(McpResourcePayload):
    thread: ResearchOutputSummary
    reader_url: str | None = Field(
        default=None,
        max_length=READER_URL_MAX_LENGTH,
        description=READER_URL_DESCRIPTION,
    )


class ResearchOutputResourcePayload(McpResourcePayload):
    research_output: ResearchOutputSummary
    reader_url: str | None = Field(
        default=None,
        max_length=READER_URL_MAX_LENGTH,
        description=READER_URL_DESCRIPTION,
    )


type ScholensResourcePayload = (
    LibraryResourcePayload
    | ProjectIndexResourcePayload
    | ProjectResourcePayload
    | PaperResourcePayload
    | AnnotationThreadResourcePayload
    | ResearchOutputResourcePayload
)


@dataclass(frozen=True, slots=True)
class ResourceContract:
    """One discoverable Resource or Resource Template public contract."""

    uri: str
    name: str
    title: str
    description: str
    payload_model: type[McpResourcePayload]
    mime_type: str = "application/json"


MCP_RESOURCE_MAX_UTF8_BYTES = 200_000

STATIC_RESOURCE_CONTRACTS = (
    ResourceContract(
        uri="scholens://library",
        name="library",
        title="Personal Scholens Library",
        description=(
            "Bounded manifest of saved papers, active ingestions, stored outputs, "
            "and attention counts."
        ),
        payload_model=LibraryResourcePayload,
    ),
    ResourceContract(
        uri="scholens://projects",
        name="projects",
        title="Accessible Scholens Projects",
        description=(
            "Bounded Project index for restoring repository-to-Scholens bindings."
        ),
        payload_model=ProjectIndexResourcePayload,
    ),
)

RESOURCE_TEMPLATE_CONTRACTS = (
    ResourceContract(
        uri="scholens://papers/{document_id}",
        name="paper",
        title="Scholens paper",
        description="Canonical metadata and a bounded extracted-text preview.",
        payload_model=PaperResourcePayload,
    ),
    ResourceContract(
        uri="scholens://projects/{project_id}",
        name="project",
        title="Scholens Project",
        description="Durable long-running research Project manifest.",
        payload_model=ProjectResourcePayload,
    ),
    ResourceContract(
        uri="scholens://annotation-threads/{thread_id}",
        name="annotation-thread",
        title="Scholens annotation thread",
        description="Anchored quote and visible collaborative discussion.",
        payload_model=AnnotationThreadResourcePayload,
    ),
    ResourceContract(
        uri="scholens://research-outputs/{item_id}",
        name="research-output",
        title="Scholens research output",
        description="Existing annotation thread, citation, audio overview, or data table.",
        payload_model=ResearchOutputResourcePayload,
    ),
)


__all__ = [
    "AnnotationThreadResourcePayload",
    "LibraryPaperResourceEntry",
    "LibraryPaperResourceIngestionEntryModel",
    "LibraryPaperResourceList",
    "LibraryPaperResourcePaperEntryModel",
    "LibraryResourcePayload",
    "MCP_RESOURCE_MAX_UTF8_BYTES",
    "RESOURCE_TEMPLATE_CONTRACTS",
    "ResourceContract",
    "PaperContentPreview",
    "PaperResourcePayload",
    "ProjectIndexResourcePayload",
    "ProjectPaperResourceList",
    "ProjectPaperResourceSummary",
    "ProjectResourcePayload",
    "ResearchOutputSummaryResource",
    "ResearchOutputSummaryResourceList",
    "ResearchOutputResourcePayload",
    "ResourceContinuation",
    "ScholensResourcePayload",
    "STATIC_RESOURCE_CONTRACTS",
    "TruncatedResourcePayload",
]
