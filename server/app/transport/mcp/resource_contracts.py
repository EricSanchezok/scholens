"""Typed public payloads for Scholens MCP resource reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.shared.domain import JsonValue

from app.modules.papers.application.contracts.documents import (
    DocumentResponse,
    LibraryPaperListResponse,
    LibrarySummaryResponse,
)
from app.modules.projects.application.contracts import (
    ProjectCollaboratorListResponse,
    ProjectListResponse,
    ProjectPaperListResponse,
    ProjectResponse,
)
from app.modules.research.application.contracts import (
    ResearchOutputSummary,
    ResearchOutputSummaryListResponse,
)
from pydantic import BaseModel, ConfigDict, Field


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


class LibraryResourcePayload(McpResourcePayload):
    summary: LibrarySummaryResponse
    papers: LibraryPaperListResponse
    research_outputs: ResearchOutputSummaryListResponse


class ProjectIndexResourcePayload(McpResourcePayload):
    projects: ProjectListResponse


class ProjectResourcePayload(McpResourcePayload):
    project: ProjectResponse
    papers: ProjectPaperListResponse
    members: ProjectCollaboratorListResponse
    research_outputs: ResearchOutputSummaryListResponse


class PaperContentPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_line: int = Field(ge=1)
    end_line: int = Field(ge=0)
    total_lines: int = Field(ge=0)
    lines: list[str]
    truncated: bool


class PaperResourcePayload(McpResourcePayload):
    paper: DocumentResponse
    content_preview: PaperContentPreview
    projects: ProjectListResponse


class AnnotationThreadResourcePayload(McpResourcePayload):
    thread: ResearchOutputSummary


class ResearchOutputResourcePayload(McpResourcePayload):
    research_output: ResearchOutputSummary


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
    "LibraryResourcePayload",
    "MCP_RESOURCE_MAX_UTF8_BYTES",
    "RESOURCE_TEMPLATE_CONTRACTS",
    "ResourceContract",
    "PaperContentPreview",
    "PaperResourcePayload",
    "ProjectIndexResourcePayload",
    "ProjectResourcePayload",
    "ResearchOutputResourcePayload",
    "ResourceContinuation",
    "ScholensResourcePayload",
    "STATIC_RESOURCE_CONTRACTS",
    "TruncatedResourcePayload",
]
