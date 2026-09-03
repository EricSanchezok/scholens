"""Agent-facing contracts for the canonical Scholens research tools.

Descriptions in this module teach a model how to choose and compose tools. They
intentionally avoid persistence, transport, and implementation details.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.modules.action_confirmations.contracts import ConfirmationChallenge
from app.modules.jobs.application.contracts import JobResponse
from app.modules.papers.application.contracts.citation import (
    CitationMethod,
    StepKind,
)
from app.modules.papers.application.contracts.documents import (
    DocumentMetadataOverrides,
    LibraryPaperIngestionResponse,
    LibraryPaperListResponse,
    LibraryOutputSort,
    LibraryOutputResponse,
    LibraryPaperResponse,
    LibraryPaperSort,
)
from app.modules.papers.application.contracts.search import (
    PaperSearchFilters,
    PaperSearchSort,
)
from app.modules.papers.application.contracts.tags import LibraryTagResponse
from app.modules.papers.application.contracts.uploads import PaperSource
from app.modules.projects.application.contracts import (
    ProjectCollaboratorListResponse,
    ProjectInvitationResponse,
    ProjectListResponse,
    ProjectPaperListResponse,
    ProjectPaperSort,
    ProjectPermissionSet,
    ProjectResponse,
    ProjectSort,
)
from app.modules.research.application.contracts import (
    AnnotationAudience,
    AnnotationCommentResponse,
    AnnotationThreadSummaryResponse,
    PersonalResearchAudience,
    ResearchItemResponse,
    UPDATE_ANNOTATION_THREAD_JSON_SCHEMA_EXTRA,
)
from app.modules.research.application.positions import ResearchPosition
from app.shared.domain import JsonValue
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationAudienceFilter,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    JobOperation,
    PaperStatus,
    ResearchItemKind,
)
from pydantic import BaseModel, ConfigDict, EmailStr, Field, RootModel, model_validator

PROJECT_ID_DESCRIPTION = (
    "The immutable Scholens Project UUID. In a repository-bound workflow, read it "
    "from AGENTS.md or README, or obtain it from a Project tool. Never infer it from "
    "the mutable Project title."
)
DOCUMENT_ID_DESCRIPTION = (
    "The immutable Scholens document UUID returned by an ingestion, search, list, or "
    "paper tool. Do not substitute a DOI, title, filename, or external provider ID."
)
CURSOR_DESCRIPTION = (
    "An opaque cursor returned by the previous call with the same filters. Return it "
    "unchanged; do not parse, edit, or reuse it with different filters."
)
IDEMPOTENCY_DESCRIPTION = (
    "A client-generated stable key for this one logical mutation. Reuse the exact key "
    "after a timeout or lost response; use a new key for a genuinely new action."
)
CONFIRMATION_DESCRIPTION = (
    "The short-lived token returned by this same tool's impact preview. Omit it on the "
    "first call. Show the preview to the user and retry with unchanged business "
    "arguments only after approval."
)
WAIT_SECONDS_DESCRIPTION = (
    "Maximum time to await terminal job status before returning the latest durable "
    "snapshot. Use 0 for an immediate snapshot. Do not implement rapid polling."
)

ProjectId = Annotated[UUID, Field(description=PROJECT_ID_DESCRIPTION)]
DocumentId = Annotated[UUID, Field(description=DOCUMENT_ID_DESCRIPTION)]
ScholensUserId = Annotated[int, Field(gt=0, le=(1 << 63) - 1)]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MutationInput(ToolInput):
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description=IDEMPOTENCY_DESCRIPTION,
    )


class WaitableMutationInput(MutationInput):
    wait_seconds: int = Field(
        default=30,
        ge=0,
        le=240,
        description=WAIT_SECONDS_DESCRIPTION,
    )


class ConfirmedMutationInput(MutationInput):
    confirmation_token: str | None = Field(
        default=None,
        min_length=32,
        max_length=256,
        description=CONFIRMATION_DESCRIPTION,
    )


class EmptyInput(ToolInput):
    pass


class DocumentInput(ToolInput):
    document_id: DocumentId


class JsonDocumentPageInput(ToolInput):
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=CURSOR_DESCRIPTION,
    )
    max_utf8_bytes: int = Field(
        default=24_000,
        ge=1_024,
        le=32_000,
        description=(
            "Maximum UTF-8 bytes from the canonical JSON document to return. "
            "Continue with next_cursor until complete is true."
        ),
    )


class PaperMetadataPageInput(DocumentInput, JsonDocumentPageInput):
    pass


class LibraryPaperPageInput(DocumentInput, JsonDocumentPageInput):
    pass


class JsonDocumentPageOutput(BaseModel):
    representation: Literal["utf8_json_page"] = "utf8_json_page"
    resource_uri: str = Field(min_length=1, max_length=512)
    media_type: Literal["application/json"] = "application/json"
    content: str = Field(
        max_length=32_000,
        description=(
            "An exact UTF-8 fragment. Concatenate content from consecutive pages "
            "in byte-offset order, then parse the resulting JSON document."
        ),
    )
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_utf8_byte: int = Field(ge=0)
    end_utf8_byte: int = Field(ge=0)
    total_utf8_bytes: int = Field(ge=0)
    complete: bool
    next_cursor: str | None = None
    access_url: str | None = Field(
        default=None,
        max_length=2_048,
        description=(
            "Short-lived access URL for a related binary artifact, when one exists. "
            "It is intentionally outside the canonical paged JSON document."
        ),
    )
    guidance: str = Field(max_length=500)


class ProjectInput(ToolInput):
    project_id: ProjectId


class ListProjectMembersInput(ProjectInput):
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=CURSOR_DESCRIPTION,
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Maximum visible Project members to return in this page.",
    )


class ListProjectInvitationsInput(ProjectInput):
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=CURSOR_DESCRIPTION,
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=20,
        description="Maximum active Project invitations to return in this page.",
    )


class ProjectInvitationToolResponse(ProjectInvitationResponse):
    project_name: str = Field(max_length=512)
    invited_by: str = Field(max_length=512)


class ProjectInvitationListOutput(BaseModel):
    items: list[ProjectInvitationToolResponse] = Field(max_length=20)
    next_cursor: str | None = Field(default=None, max_length=2_048)
    content_truncated: bool = False
    guidance: str = Field(max_length=500)


class ListPaperProjectsInput(DocumentInput):
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=CURSOR_DESCRIPTION,
    )
    limit: int = Field(
        default=25,
        ge=1,
        le=25,
        description="Maximum accessible Projects to return in this page.",
    )


class LibraryKnowledgeScope(ToolInput):
    kind: Literal["library"] = Field(
        default="library",
        description="Search only the current user's personal Library membership.",
    )


class AllAccessibleKnowledgeScope(ToolInput):
    kind: Literal["all_accessible"] = Field(
        default="all_accessible",
        description="Search personal Library papers and every accessible Project.",
    )


class ProjectKnowledgeScope(ToolInput):
    kind: Literal["project"] = Field(
        default="project",
        description="Search exactly one Project's stored research knowledge.",
    )
    project_id: ProjectId


class PaperKnowledgeScope(ToolInput):
    kind: Literal["paper"] = Field(
        default="paper",
        description="Search within one already-stored Scholens paper.",
    )
    document_id: DocumentId
    project_id: ProjectId | None = Field(
        default=None,
        description=(
            "Optional Project context for this paper. Supply it when the query should "
            "include Project-shared annotations rather than only the caller's personal ones."
        ),
    )


KnowledgeScope = Annotated[
    LibraryKnowledgeScope
    | AllAccessibleKnowledgeScope
    | ProjectKnowledgeScope
    | PaperKnowledgeScope,
    Field(discriminator="kind"),
]


class SearchKnowledgeInput(ToolInput):
    query: str = Field(
        min_length=2,
        max_length=1_000,
        description=(
            "What to find inside knowledge already stored in Scholens. This searches "
            "saved paper metadata and text, annotations, comments, and existing research "
            "outputs; it never discovers papers on the internet."
        ),
    )
    scope: KnowledgeScope = Field(
        description=(
            "The explicit Scholens boundary to search. Prefer project for a repository "
            "that is bound to one long-running research Project. Always pass one of "
            'these object shapes: {"kind":"library"}, '
            '{"kind":"all_accessible"}, '
            '{"kind":"project","project_id":"<uuid>"}, or '
            '{"kind":"paper","document_id":"<uuid>"}; the paper shape may also '
            'include "project_id":"<uuid>".'
        ),
        examples=[
            {"kind": "library"},
            {"kind": "all_accessible"},
            {"kind": "project", "project_id": "00000000-0000-0000-0000-000000000000"},
            {"kind": "paper", "document_id": "00000000-0000-0000-0000-000000000000"},
        ],
    )
    kinds: list[
        Literal[
            "paper",
            "paper_passage",
            "annotation_thread",
            "annotation_comment",
            "research_output",
        ]
    ] = Field(
        default_factory=list,
        max_length=5,
        description="Optional result kinds to include; an empty list includes all kinds.",
    )
    filters: PaperSearchFilters = Field(
        default_factory=PaperSearchFilters,
        description="Optional publication-date filters applied only to paper results.",
    )
    sort: PaperSearchSort = Field(
        default=PaperSearchSort.RELEVANCE,
        description="Rank by textual relevance or by recent activity.",
    )
    cursor: str | None = Field(
        default=None, max_length=2_048, description=CURSOR_DESCRIPTION
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description=(
            "Requested maximum combined results. The public UTF-8 envelope may return "
            "a smaller page with next_cursor; continue until next_cursor is null."
        ),
    )


class KnowledgeSearchResult(BaseModel):
    kind: Literal[
        "paper",
        "paper_passage",
        "annotation_thread",
        "annotation_comment",
        "research_output",
    ]
    resource_uri: str
    title: str | None = None
    excerpt: str = Field(
        description="UTF-8/JSON-bounded evidence preview; open the resource for full text."
    )
    score: float = Field(ge=0)
    document_id: UUID | None = None
    project_id: UUID | None = None
    entity_id: UUID
    locator: dict[str, JsonValue] | None = None
    updated_at: datetime


class KnowledgeSearchOutput(BaseModel):
    items: list[KnowledgeSearchResult]
    next_cursor: str | None = None
    searched_scope: KnowledgeScope
    guidance: str = (
        "Use get_paper_content for surrounding paper text and get_annotation_thread or "
        "get_research_output for the complete stored item."
    )


class PaperContentInput(DocumentInput):
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=(
            "Opaque continuation returned by the previous page. When present, "
            "start_line must remain at its default."
        ),
    )
    start_line: int = Field(
        default=1,
        ge=1,
        le=(1 << 63) - 1,
        description=(
            "One-based first extracted-text line for a new read; continuation "
            "requests use cursor instead."
        ),
    )
    max_lines: int = Field(
        default=200,
        ge=1,
        le=500,
        description=(
            "Maximum lines to return. Read incrementally using next_cursor instead of "
            "requesting an entire paper at once; the UTF-8 budget may stop earlier."
        ),
    )
    max_utf8_bytes: int = Field(
        default=32_768,
        ge=1_024,
        le=32_768,
        description=(
            "Maximum UTF-8 bytes of exact extracted text before JSON-envelope "
            "overhead; continuation remains lossless."
        ),
    )


class PaperContentOutput(BaseModel):
    document_id: UUID
    title: str | None
    title_truncated: bool = Field(
        default=False,
        description=(
            "Whether title is a bounded display preview; get_paper_page is lossless."
        ),
    )
    start_line: int
    end_line: int | None
    total_lines: int
    lines: list[str]
    next_start_line: int | None
    content_sha256: str | None
    content: str
    content_utf8_bytes: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    starts_mid_line: bool
    ends_mid_line: bool
    next_cursor: str | None
    truncated: bool
    guidance: str


class SearchPaperContentInput(DocumentInput):
    query: str = Field(
        min_length=1,
        max_length=2_000,
        description=(
            "Text or regular expression to locate inside this paper's extracted text. "
            "Use search_scholens_knowledge when you do not already know the paper UUID."
        ),
    )
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=(
            "Opaque continuation returned by a previous search page. It is bound "
            "to the actor, paper, query, and exact content digest."
        ),
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum bounded matching lines to return in this page.",
    )


class PaperContentSearchOutput(BaseModel):
    document_id: UUID
    matches: list[str] = Field(max_length=20)
    match_count: int = Field(ge=0)
    total_match_count: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Cumulative match count once the final page is reached; null while "
            "additional pages remain."
        ),
    )
    next_cursor: str | None = Field(default=None, max_length=2_048)
    truncated: bool = False
    guidance: str


class PaperCitationInput(DocumentInput):
    style: str = Field(
        default="APA",
        min_length=1,
        max_length=100,
        description=(
            "Preferred citation-style key, for example APA. This selects presentation "
            "metadata; it is not a free-form formatting instruction."
        ),
    )
    project_id: ProjectId | None = Field(
        default=None,
        description="Optional Project context used to authorize a Project-only paper.",
    )


CITATION_MAX_AUTHORS = 20
CITATION_MAX_STEPS = 8
CITATION_MAX_MAP_ITEMS = 8
CITATION_TEXT_MAX_CHARACTERS = 2_048
CITATION_FIELD_MAX_CHARACTERS = 1_024
CITATION_AUTHOR_MAX_CHARACTERS = 256
CITATION_STEP_DETAIL_MAX_CHARACTERS = 512


class CitationDataOutput(BaseModel):
    document_id: str = Field(max_length=64)
    title: str | None = Field(default=None, max_length=CITATION_TEXT_MAX_CHARACTERS)
    authors: list[Annotated[str, Field(max_length=CITATION_AUTHOR_MAX_CHARACTERS)]] = (
        Field(default_factory=list, max_length=CITATION_MAX_AUTHORS)
    )
    publish_date: str | None = Field(
        default=None,
        max_length=CITATION_FIELD_MAX_CHARACTERS,
    )
    journal: str | None = Field(
        default=None,
        max_length=CITATION_FIELD_MAX_CHARACTERS,
    )
    publisher: str | None = Field(
        default=None,
        max_length=CITATION_FIELD_MAX_CHARACTERS,
    )
    doi: str | None = Field(
        default=None,
        max_length=CITATION_FIELD_MAX_CHARACTERS,
    )


class CitationStepOutput(BaseModel):
    kind: StepKind
    detail: str = Field(max_length=CITATION_STEP_DETAIL_MAX_CHARACTERS)
    data: dict[str, JsonValue] | None = Field(
        default=None,
        max_length=CITATION_MAX_MAP_ITEMS,
    )
    data_truncated: bool = False


class PaperCitationReadOutput(BaseModel):
    document_id: UUID
    preferred_style: str = Field(max_length=100)
    data: CitationDataOutput
    missing_fields: list[Annotated[str, Field(max_length=128)]] = Field(
        max_length=CITATION_MAX_MAP_ITEMS
    )
    complete: bool
    content_truncated: bool = False
    guidance: str = Field(max_length=1_000)


class ResolvePaperCitationInput(MutationInput):
    document_id: DocumentId
    style: str = Field(
        default="APA",
        min_length=1,
        max_length=100,
        description=(
            "Preferred citation-style key, for example APA. Resolution recovers and "
            "persists missing bibliographic fields; it does not generate prose."
        ),
    )
    project_id: ProjectId | None = Field(
        default=None,
        description="Optional Project context used to authorize a Project-only paper.",
    )


class ListProjectsInput(ToolInput):
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=240,
        description="Optional title or description text to match among accessible Projects.",
    )
    sort: ProjectSort = Field(
        default=ProjectSort.ACTIVITY_DESC,
        description="Project ordering for this page.",
    )
    cursor: str | None = Field(
        default=None, max_length=2_048, description=CURSOR_DESCRIPTION
    )
    limit: int = Field(default=20, ge=1, le=100, description="Page size.")


class CreateProjectInput(MutationInput):
    title: str = Field(
        min_length=1,
        max_length=240,
        description=(
            "Human-readable Project name. Titles are mutable and need not be unique; "
            "store the returned UUID as the durable repository binding."
        ),
    )
    description: str | None = Field(
        default=None,
        max_length=10_000,
        description="Optional concise research objective, boundary, or collaboration note.",
    )


class UpdateProjectInput(MutationInput):
    project_id: ProjectId
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=240,
        description="Replacement Project title; omit it to retain the current title.",
    )
    description: str | None = Field(
        default=None,
        max_length=10_000,
        description=(
            "Replacement Project description. Send null explicitly to clear it; omit "
            "the field to retain the current description."
        ),
    )

    @model_validator(mode="after")
    def require_change(self) -> UpdateProjectInput:
        if self.title is None and "description" not in self.model_fields_set:
            raise ValueError("provide title or description")
        return self


class DeleteProjectInput(ConfirmedMutationInput):
    project_id: ProjectId


class ProjectToolResponse(ProjectResponse):
    resource_uri: str
    web_url: str
    binding_markdown: str
    content_truncated: bool = Field(
        default=False,
        description=(
            "Whether unsupported historical Project or owner display text was bounded."
        ),
    )
    guidance: str | None = Field(
        default=None,
        description="How to normalize an unsupported historical Project value.",
    )


class ProjectListToolOutput(ProjectListResponse):
    content_truncated: bool = Field(
        description="True when one or more Project text fields are bounded previews."
    )
    guidance: str = Field(
        max_length=500,
        description="How to retrieve complete Project content and continue pagination.",
    )


class ProjectMemberListToolOutput(ProjectCollaboratorListResponse):
    content_truncated: bool = Field(
        description="True when one or more collaborator identity fields are previews."
    )
    guidance: str = Field(
        max_length=500,
        description="How to continue and address members by immutable user ID.",
    )


class ProjectPaperListToolOutput(ProjectPaperListResponse):
    content_truncated: bool = Field(
        description="True when one or more paper metadata fields are bounded previews."
    )
    guidance: str = Field(
        max_length=500,
        description="How to retrieve complete paper content and continue pagination.",
    )


class ListProjectPapersInput(ProjectInput):
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Optional metadata text to match within this Project.",
    )
    sort: ProjectPaperSort = Field(
        default=ProjectPaperSort.ADDED_DESC,
        description="Ordering for this page of Project papers.",
    )
    cursor: str | None = Field(
        default=None, max_length=2_048, description=CURSOR_DESCRIPTION
    )
    limit: int = Field(default=20, ge=1, le=100, description="Page size.")


class AddPapersToProjectInput(MutationInput):
    project_id: ProjectId
    document_ids: list[UUID] = Field(
        min_length=1,
        max_length=120,
        description=(
            "Unique Scholens document UUIDs already accessible to the caller. Use "
            "ingest_paper for a DOI, arXiv ID, URL, or uploaded PDF instead."
        ),
    )


class ProjectPaperInput(ConfirmedMutationInput):
    project_id: ProjectId
    document_id: DocumentId


class MemberInput(ProjectInput):
    user_id: ScholensUserId = Field(
        description="The immutable Scholens user ID returned by list_project_members.",
    )


class UpdateProjectMemberInput(ConfirmedMutationInput):
    project_id: ProjectId
    user_id: ScholensUserId = Field(
        description="Collaborator user ID returned by list_project_members."
    )
    edit_project: bool = Field(description="Allow changing Project metadata.")
    manage_papers: bool = Field(description="Allow adding and removing Project papers.")
    manage_collaborators: bool = Field(
        description="Allow managing Project collaborators and invitations."
    )


class RemoveProjectMemberInput(ConfirmedMutationInput):
    project_id: ProjectId
    user_id: ScholensUserId = Field(
        description="Collaborator user ID returned by list_project_members."
    )


class LeaveProjectInput(ConfirmedMutationInput):
    project_id: ProjectId


class TransferProjectOwnershipInput(ConfirmedMutationInput):
    project_id: ProjectId
    new_owner_id: ScholensUserId = Field(
        description=(
            "User ID of an existing Project collaborator who should become owner. "
            "Obtain it from list_project_members."
        ),
    )


class CreateProjectInvitationInput(ConfirmedMutationInput):
    project_id: ProjectId
    email: EmailStr = Field(
        description="Exact email address of the intended collaborator."
    )
    edit_project: bool = Field(description="Allow changing Project metadata.")
    manage_papers: bool = Field(description="Allow adding and removing Project papers.")
    manage_collaborators: bool = Field(
        description="Allow managing Project collaborators and invitations."
    )


class InvitationInput(ConfirmedMutationInput):
    project_id: ProjectId
    invitation_id: UUID = Field(
        description="Invitation UUID returned by list_project_invitations."
    )


class AcceptProjectInvitationInput(ConfirmedMutationInput):
    token: str = Field(
        min_length=16,
        max_length=1_024,
        description=(
            "The exact invitation token delivered to the current user's email. Never "
            "use an invitation UUID or another person's token."
        ),
    )


class ListLibraryPapersInput(ToolInput):
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Optional metadata text to match in the personal Library.",
    )
    tag_ids: list[UUID] = Field(
        default_factory=list,
        max_length=100,
        description="Optional tag UUIDs from list_library_tags; empty includes all tags.",
    )
    sort: LibraryPaperSort = Field(
        default=LibraryPaperSort.ADDED_DESC,
        description="Ordering for this page of personal Library papers.",
    )
    cursor: str | None = Field(
        default=None, max_length=2_048, description=CURSOR_DESCRIPTION
    )
    limit: int = Field(default=20, ge=1, le=100, description="Page size.")


class LibraryPaperListToolOutput(LibraryPaperListResponse):
    content_truncated: bool = Field(
        description="True when one or more Library item fields are bounded previews."
    )
    guidance: str = Field(
        max_length=500,
        description="How to retrieve lossless Library paper JSON and continue pages.",
    )


class LibraryPaperToolOutput(LibraryPaperResponse):
    content_truncated: bool = Field(
        description="True when one or more Library or document fields are previews."
    )
    guidance: str = Field(
        max_length=500,
        description="How to retrieve the lossless Library paper representation.",
    )


class UpdateLibraryPaperInput(MutationInput):
    document_id: DocumentId
    status: PaperStatus | None = Field(
        default=None,
        description="Optional personal reading status; omit to retain the current status.",
    )
    metadata_overrides: DocumentMetadataOverrides | None = Field(
        default=None,
        description=(
            "Personal Library metadata overrides. This does not rewrite canonical "
            "metadata seen by collaborators."
        ),
    )


class RemoveLibraryPapersInput(ConfirmedMutationInput):
    document_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
        description=(
            "Paper UUIDs to remove from the personal Library. Repeated UUIDs are "
            "accepted for compatibility and treated as one paper. Project copies and "
            "the shared document records are not deleted."
        ),
    )


class CollectProjectPaperInput(MutationInput):
    source_project_id: ProjectId
    document_id: DocumentId


class SharedPaperInput(ConfirmedMutationInput):
    document_id: DocumentId


class CollectSharedPaperInput(MutationInput):
    share_token: str = Field(
        min_length=1,
        max_length=512,
        description="Public Scholens share token supplied by the paper owner.",
    )


class ListLibraryTagsInput(ToolInput):
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=CURSOR_DESCRIPTION,
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum personal Library tags to return in this page.",
    )


class LibraryTagToolResponse(LibraryTagResponse):
    name: str = Field(max_length=256)
    color: str | None = Field(max_length=256)


class LibraryTagListOutput(BaseModel):
    items: list[LibraryTagToolResponse] = Field(max_length=50)
    next_cursor: str | None = Field(default=None, max_length=2_048)
    content_truncated: bool = False
    guidance: str = Field(max_length=500)


class CreateLibraryTagInput(MutationInput):
    name: str = Field(
        min_length=1,
        max_length=80,
        description="Concise personal tag name used to organize Library papers.",
    )


class UpdateLibraryTagInput(MutationInput):
    tag_id: UUID = Field(description="Tag UUID returned by list_library_tags.")
    name: str = Field(
        min_length=1,
        max_length=80,
        description="Replacement personal tag name.",
    )


class DeleteLibraryTagInput(ConfirmedMutationInput):
    tag_id: UUID = Field(description="Tag UUID returned by list_library_tags.")


class ReplaceLibraryPaperTagsInput(MutationInput):
    document_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
        description="Unique Library paper UUIDs whose complete tag set will be replaced.",
    )
    tag_ids: list[UUID] = Field(
        default_factory=list,
        max_length=100,
        description="Complete desired tag UUID set; an empty list removes all tags.",
    )


class IngestPaperInput(WaitableMutationInput):
    source: PaperSource = Field(
        description=(
            "One already-known paper source. Use this for import, never for discovery. "
            "For a local PDF, first obtain an upload_id through the upload helper."
        )
    )
    project_id: ProjectId | None = Field(
        default=None,
        description=(
            "Optional destination Project. Omit it to add the paper only to the "
            "caller's personal Library. For source.kind=upload, repeat the exact value "
            "used to prepare that upload; omit it only when the upload was prepared for "
            "the personal Library."
        ),
    )
    add_to_library: bool = Field(
        default_factory=lambda: True,
        description=(
            "When true and a Project is targeted, the completed paper is also "
            "added to the caller's personal Library. Set false to keep it "
            "Project-only. Requires project_id."
        ),
    )


class RetryPaperIngestionInput(WaitableMutationInput):
    job_id: UUID = Field(description="Failed ingestion job UUID returned by get_job.")


class IngestPapersInput(WaitableMutationInput):
    sources: list[PaperSource] = Field(
        min_length=1,
        max_length=50,
        description=(
            "One to fifty already-known paper sources to ingest as one bounded batch. "
            "Input order is preserved in the result."
        ),
    )
    project_id: ProjectId | None = Field(
        default=None,
        description=(
            "Optional destination Project applied to every source. Omit it to add the "
            "papers only to the caller's personal Library. Upload sources must have "
            "been prepared for this exact destination."
        ),
    )
    add_to_library: bool = Field(
        default_factory=lambda: True,
        description=(
            "When true and a Project is targeted, completed papers are also added to "
            "the caller's personal Library. Set false for Project-only ingestion."
        ),
    )


class CancelPaperIngestionInput(ConfirmedMutationInput):
    job_id: UUID = Field(description="Pending or running ingestion job UUID to cancel.")


class ListJobsInput(ToolInput):
    project_id: ProjectId | None = Field(
        default=None, description="Optional Project UUID used to narrow the job list."
    )
    document_id: DocumentId | None = Field(
        default=None, description="Optional paper UUID used to narrow the job list."
    )
    operation: JobOperation | None = Field(
        default=None, description="Optional asynchronous operation type to include."
    )
    active: bool = Field(
        default=False,
        description="When true, return only pending or running jobs.",
    )
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=CURSOR_DESCRIPTION,
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum number of durable job status snapshots to return.",
    )


class JobInput(ToolInput):
    job_id: UUID = Field(description="Job UUID returned by an asynchronous tool.")


class GetJobInput(JobInput):
    wait_seconds: int = Field(
        default=30,
        ge=0,
        le=240,
        description=WAIT_SECONDS_DESCRIPTION,
    )


class WaitForJobsInput(ToolInput):
    job_ids: list[UUID] = Field(
        min_length=1,
        max_length=50,
        description=(
            "One to fifty durable job UUIDs to observe together. Pass only active job "
            "IDs returned by earlier tools."
        ),
    )
    wait_seconds: int = Field(
        default=120,
        ge=0,
        le=240,
        description=WAIT_SECONDS_DESCRIPTION,
    )


class JobWaitMetadata(BaseModel):
    outcome: Literal["completed", "failed", "cancelled", "timed_out"]
    requested_seconds: int = Field(ge=0, le=240)
    elapsed_ms: int = Field(ge=0)
    next_action: Literal["use_result", "inspect_failure", "stop", "wait_again"]
    guidance: str


class WaitableJobResponse(JobResponse):
    wait: JobWaitMetadata


class PaperIngestionToolResponse(LibraryPaperIngestionResponse):
    job: WaitableJobResponse


class JobBatchWaitMetadata(BaseModel):
    outcome: Literal["all_terminal", "timed_out"]
    requested_seconds: int = Field(ge=0, le=240)
    elapsed_ms: int = Field(ge=0)
    next_action: Literal["inspect_items", "wait_for_remaining"]
    guidance: str


class WaitForJobsResponse(BaseModel):
    items: list[WaitableJobResponse]
    wait: JobBatchWaitMetadata


class BatchPaperIngestionItem(BaseModel):
    index: int = Field(ge=0)
    source: PaperSource
    source_truncated: bool = Field(
        default=False,
        description=(
            "True when source is a bounded UTF-8-safe receipt preview. Match the "
            "item by index and continue with its job or document UUID; never retry "
            "ingestion from a truncated preview."
        ),
    )
    status: Literal["accepted", "rejected"]
    ingestion: LibraryPaperIngestionResponse | None = None
    job: WaitableJobResponse | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "BatchPaperIngestionItem":
        if self.status == "accepted" and (
            self.ingestion is None or self.job is None or self.error_code is not None
        ):
            raise ValueError("accepted batch items require ingestion and job results")
        if self.status == "rejected" and (
            self.ingestion is not None
            or self.job is not None
            or self.error_code is None
        ):
            raise ValueError("rejected batch items require only an error code")
        return self


class BatchPaperIngestionSummary(BaseModel):
    requested: int = Field(ge=1, le=50)
    accepted: int = Field(ge=0, le=50)
    rejected: int = Field(ge=0, le=50)
    active: int = Field(ge=0, le=50)
    completed: int = Field(ge=0, le=50)
    failed: int = Field(ge=0, le=50)
    cancelled: int = Field(ge=0, le=50)


class BatchPaperIngestionResponse(BaseModel):
    items: list[BatchPaperIngestionItem]
    summary: BatchPaperIngestionSummary
    wait: JobBatchWaitMetadata


class ListAnnotationThreadsInput(DocumentInput):
    project_id: ProjectId | None = Field(
        default=None,
        description="Optional Project context for Project-visible annotation threads.",
    )
    audience: AnnotationAudienceFilter | None = Field(
        default=None,
        description="Optional visibility boundary; omit to include all visible audiences.",
    )
    mode: AnnotationThreadMode | None = Field(
        default=None, description="Optional Reader annotation-mode filter."
    )
    status: AnnotationThreadStatus = Field(
        default=AnnotationThreadStatus.OPEN,
        description="Thread status to include; defaults to open discussions.",
    )
    cursor: str | None = Field(
        default=None,
        max_length=2_048,
        description=CURSOR_DESCRIPTION,
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum annotation-thread summaries to return in this page.",
    )


class AnnotationThreadInput(ToolInput):
    thread_id: UUID = Field(
        description="Annotation-thread UUID returned by a search or annotation tool."
    )


class AnnotationThreadPageInput(AnnotationThreadInput, JsonDocumentPageInput):
    cursor: str | None = Field(
        default=None, max_length=2_048, description=CURSOR_DESCRIPTION
    )
    max_utf8_bytes: int = Field(
        default=24_000,
        ge=1_024,
        le=32_000,
        description="Maximum UTF-8 bytes of thread JSON to return in this page.",
    )


class CreateAnnotationThreadInput(MutationInput):
    document_id: DocumentId
    quote_text: str = Field(
        min_length=1,
        max_length=100_000,
        description="Exact visible paper text being marked; do not fabricate a quote.",
    )
    position: ResearchPosition = Field(
        description="Reader position that anchors quote_text to the stored PDF."
    )
    color: AnnotationColor = Field(
        default=AnnotationColor.YELLOW,
        description="Reader highlight color for this thread.",
    )
    audience: AnnotationAudience = Field(
        description="Personal or Project visibility for the annotation thread."
    )
    initial_comment: str | None = Field(
        default=None,
        min_length=1,
        max_length=100_000,
        description="Optional first discussion comment explaining the marked passage.",
    )


class AnnotatePaperInput(MutationInput):
    """High-level annotation request that resolves quote text server-side."""

    document_id: DocumentId
    quote_text: str = Field(
        min_length=1,
        max_length=100_000,
        description=(
            "Exact visible paper passage to mark. The server resolves it against "
            "canonical extracted text; do not provide PDF geometry."
        ),
    )
    comment: str | None = Field(
        default=None,
        min_length=1,
        max_length=100_000,
        description="Optional note or discussion explaining the marked passage.",
    )
    color: AnnotationColor = Field(
        default=AnnotationColor.YELLOW,
        description="Reader color for the mark; defaults to yellow.",
    )
    audience: AnnotationAudience = Field(
        default_factory=PersonalResearchAudience,
        description="Personal or Project visibility; defaults to personal.",
    )
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "Optional digest from get_paper_content. When supplied, reject a "
            "stale write instead of anchoring against changed text."
        ),
    )


class UpdateAnnotationThreadInput(MutationInput):
    model_config = ConfigDict(
        json_schema_extra=UPDATE_ANNOTATION_THREAD_JSON_SCHEMA_EXTRA
    )

    thread_id: UUID = Field(
        description="Annotation-thread UUID returned by a thread tool."
    )
    color: AnnotationColor | None = Field(
        default=None, description="Replacement highlight color."
    )
    status: AnnotationThreadStatus | None = Field(
        default=None, description="Replacement discussion status."
    )

    @model_validator(mode="after")
    def require_one_change(self) -> UpdateAnnotationThreadInput:
        if (self.color is None) == (self.status is None):
            raise ValueError("provide exactly one of color or status")
        return self


class DeleteAnnotationThreadInput(ConfirmedMutationInput):
    thread_id: UUID = Field(description="Annotation-thread UUID to delete.")


class CreateAnnotationCommentInput(MutationInput):
    thread_id: UUID = Field(description="Existing annotation-thread UUID to reply to.")
    content: str = Field(
        min_length=1,
        max_length=100_000,
        description="Substantive comment to add to the existing discussion thread.",
    )


class UpdateAnnotationCommentInput(MutationInput):
    comment_id: UUID = Field(description="Comment UUID returned by an annotation tool.")
    content: str = Field(
        min_length=1,
        max_length=100_000,
        description="Complete replacement comment text.",
    )


class DeleteAnnotationCommentInput(ConfirmedMutationInput):
    comment_id: UUID = Field(description="Comment UUID to delete.")


class LibraryOutputScope(ToolInput):
    kind: Literal["library"] = Field(
        default="library",
        description="List existing outputs visible through the personal Library.",
    )


class ProjectOutputScope(ToolInput):
    kind: Literal["project"] = Field(
        default="project",
        description="List existing outputs shared in exactly one Project.",
    )
    project_id: ProjectId


class PaperOutputScope(ToolInput):
    kind: Literal["paper"] = Field(
        default="paper",
        description="List existing outputs associated with exactly one paper.",
    )
    document_id: DocumentId
    project_id: ProjectId | None = Field(
        default=None,
        description=(
            "Optional Project context when Project-audience outputs for this paper "
            "should be included."
        ),
    )


ResearchOutputScope = Annotated[
    LibraryOutputScope | ProjectOutputScope | PaperOutputScope,
    Field(discriminator="kind"),
]


class ListResearchOutputsInput(ToolInput):
    scope: ResearchOutputScope = Field(
        description="Library, Project, or paper boundary containing the stored outputs."
    )
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=1_000,
        description="Optional text to match inside stored research-output content.",
    )
    kinds: list[ResearchItemKind] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Optional output kinds; empty includes annotation threads, citations, "
            "audio overviews, and data tables."
        ),
    )
    sort: LibraryOutputSort = Field(
        default=LibraryOutputSort.UPDATED_DESC,
        description="Ordering for this page of stored research outputs.",
    )
    cursor: str | None = Field(
        default=None, max_length=2_048, description=CURSOR_DESCRIPTION
    )
    limit: int = Field(default=20, ge=1, le=100, description="Page size.")


class ListResearchOutputSummariesInput(ListResearchOutputsInput):
    limit: int = Field(
        default=20,
        ge=1,
        le=25,
        description="Maximum bounded research-output summaries in this page.",
    )


class ResearchOutputInput(ToolInput):
    item_id: UUID = Field(
        description="Research-output UUID returned by a list or search tool."
    )


class ResearchOutputPageInput(ResearchOutputInput, JsonDocumentPageInput):
    cursor: str | None = Field(
        default=None, max_length=2_048, description=CURSOR_DESCRIPTION
    )
    max_utf8_bytes: int = Field(
        default=24_000,
        ge=1_024,
        le=32_000,
        description=(
            "Maximum UTF-8 bytes of canonical research-output JSON to return "
            "in this page."
        ),
    )


class ResearchOutputList(BaseModel):
    items: list[LibraryOutputResponse | ResearchItemResponse]
    next_cursor: str | None = None
    previous_cursor: str | None = None
    total_count: int = Field(ge=0)


class CompletedAction(BaseModel):
    status: Literal["completed"] = "completed"
    action: str
    changed: bool = True
    affected_resources: list[str] = Field(default_factory=list)
    result: dict[str, JsonValue] | None = None
    guidance: str | None = None


class ConfirmationAwareAction(RootModel[ConfirmationChallenge | CompletedAction]):
    pass


class CommentActionOutput(BaseModel):
    comment: AnnotationCommentResponse
    resource_uri: str
    content_truncated: bool = Field(
        default=False,
        description="Whether comment.content is a bounded preview of the stored value.",
    )
    guidance: str | None = Field(
        default=None,
        description="How to continue to the complete stored discussion when truncated.",
    )


class ThreadActionOutput(BaseModel):
    thread: ResearchItemResponse
    resource_uri: str
    content_truncated: bool = Field(
        default=False,
        description=(
            "Whether quote, position, or comments were reduced in this mutation receipt."
        ),
    )
    guidance: str | None = Field(
        default=None,
        description="How to continue to the complete stored thread when truncated.",
    )
    anchor: ResearchPosition | None = Field(
        default=None,
        description="Resolved compact anchor when a mutation created one automatically.",
    )
    visual_treatment: Literal["highlight", "underline"] | None = Field(
        default=None,
        description="Reader rendering: fill for a highlight, underline for a comment.",
    )
    next_action: str | None = Field(
        default=None,
        description="One bounded next step for an agent continuing this workflow.",
    )


class ThreadListOutput(BaseModel):
    items: list[AnnotationThreadSummaryResponse]
    next_cursor: str | None = None


class ResolvedCitationOutput(BaseModel):
    document_id: str = Field(max_length=64)
    preferred_style: str = Field(max_length=100)
    style_display: str = Field(max_length=100)
    data: CitationDataOutput
    method: CitationMethod
    missing_fields: list[Annotated[str, Field(max_length=128)]] = Field(
        default_factory=list,
        max_length=CITATION_MAX_MAP_ITEMS,
    )
    filled_fields: dict[str, JsonValue] = Field(
        default_factory=dict,
        max_length=CITATION_MAX_MAP_ITEMS,
    )
    confidence: float | None = Field(default=None, ge=0, le=1)
    steps: list[CitationStepOutput] = Field(
        default_factory=list,
        max_length=CITATION_MAX_STEPS,
    )
    resource_uri: str = Field(max_length=512)
    content_truncated: bool = False
    guidance: str = Field(max_length=1_000)


def project_permission_set(
    *, edit_project: bool, manage_papers: bool, manage_collaborators: bool
) -> ProjectPermissionSet:
    return ProjectPermissionSet(
        edit_project=edit_project,
        manage_papers=manage_papers,
        manage_collaborators=manage_collaborators,
    )
