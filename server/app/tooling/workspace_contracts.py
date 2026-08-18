"""Agent-facing contracts for the canonical Scholens research tools.

Descriptions in this module teach a model how to choose and compose tools. They
intentionally avoid persistence, transport, and implementation details.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.modules.action_confirmations.contracts import ConfirmationChallenge
from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationResult,
)
from app.modules.papers.application.contracts.documents import (
    DocumentMetadataOverrides,
    LibraryOutputSort,
    LibraryOutputResponse,
    LibraryPaperSort,
)
from app.modules.papers.application.contracts.search import (
    PaperSearchFilters,
    PaperSearchSort,
)
from app.modules.papers.application.contracts.uploads import PaperSource
from app.modules.projects.application.contracts import (
    ProjectPaperSort,
    ProjectPermissionSet,
    ProjectResponse,
    ProjectSort,
)
from app.modules.research.application.contracts import (
    AnnotationAudience,
    AnnotationCommentResponse,
    AnnotationThreadSummaryResponse,
    ResearchItemResponse,
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

ProjectId = Annotated[UUID, Field(description=PROJECT_ID_DESCRIPTION)]
DocumentId = Annotated[UUID, Field(description=DOCUMENT_ID_DESCRIPTION)]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MutationInput(ToolInput):
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description=IDEMPOTENCY_DESCRIPTION,
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


class ProjectInput(ToolInput):
    project_id: ProjectId


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
            "that is bound to one long-running research Project."
        )
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
        description="Maximum combined results to return in this page.",
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
    excerpt: str
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
    start_line: int = Field(
        default=1,
        ge=1,
        description="One-based first extracted-text line to return.",
    )
    max_lines: int = Field(
        default=200,
        ge=1,
        le=500,
        description=(
            "Maximum lines to return. Read incrementally using next_start_line instead "
            "of requesting an entire paper at once."
        ),
    )


class PaperContentOutput(BaseModel):
    document_id: UUID
    title: str | None
    start_line: int
    end_line: int | None
    total_lines: int
    lines: list[str]
    next_start_line: int | None
    content_sha256: str | None


class SearchPaperContentInput(DocumentInput):
    query: str = Field(
        min_length=1,
        max_length=2_000,
        description=(
            "Text or regular expression to locate inside this paper's extracted text. "
            "Use search_scholens_knowledge when you do not already know the paper UUID."
        ),
    )


class PaperContentSearchOutput(BaseModel):
    document_id: UUID
    matches: list[str]
    match_count: int = Field(ge=0)
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


class PaperCitationReadOutput(BaseModel):
    document_id: UUID
    preferred_style: str
    data: CitationData
    missing_fields: list[str]
    complete: bool
    guidance: str


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
    user_id: int = Field(
        gt=0,
        description="The immutable Scholens user ID returned by list_project_members.",
    )


class UpdateProjectMemberInput(ConfirmedMutationInput):
    project_id: ProjectId
    user_id: int = Field(
        gt=0, description="Collaborator user ID returned by list_project_members."
    )
    edit_project: bool = Field(description="Allow changing Project metadata.")
    manage_papers: bool = Field(description="Allow adding and removing Project papers.")
    manage_collaborators: bool = Field(
        description="Allow managing Project collaborators and invitations."
    )


class RemoveProjectMemberInput(ConfirmedMutationInput):
    project_id: ProjectId
    user_id: int = Field(
        gt=0, description="Collaborator user ID returned by list_project_members."
    )


class LeaveProjectInput(ConfirmedMutationInput):
    project_id: ProjectId


class TransferProjectOwnershipInput(ConfirmedMutationInput):
    project_id: ProjectId
    new_owner_id: int = Field(
        gt=0,
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
            "Unique paper UUIDs to remove from the personal Library. Project copies and "
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


class IngestPaperInput(MutationInput):
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


class RetryPaperIngestionInput(MutationInput):
    job_id: UUID = Field(description="Failed ingestion job UUID returned by get_job.")


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


class JobInput(ToolInput):
    job_id: UUID = Field(description="Job UUID returned by an asynchronous tool.")


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


class UpdateAnnotationThreadInput(MutationInput):
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
        description="Optional text to match inside already-generated output content.",
    )
    kinds: list[ResearchItemKind] = Field(
        default_factory=list,
        max_length=3,
        description="Optional output kinds; empty includes every research-output kind.",
    )
    sort: LibraryOutputSort = Field(
        default=LibraryOutputSort.UPDATED_DESC,
        description="Ordering for this page of stored research outputs.",
    )
    cursor: str | None = Field(
        default=None, max_length=2_048, description=CURSOR_DESCRIPTION
    )
    limit: int = Field(default=20, ge=1, le=100, description="Page size.")

    @model_validator(mode="after")
    def reject_annotation_kind(self) -> ListResearchOutputsInput:
        if ResearchItemKind.ANNOTATION_THREAD in self.kinds:
            raise ValueError(
                "annotation_thread is managed by the annotation tools, not research outputs"
            )
        return self


class ResearchOutputInput(ToolInput):
    item_id: UUID = Field(
        description="Research-output UUID returned by a list or search tool."
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


class ThreadActionOutput(BaseModel):
    thread: ResearchItemResponse
    resource_uri: str


class ThreadListOutput(BaseModel):
    items: list[AnnotationThreadSummaryResponse]
    next_cursor: str | None = None


class ResolvedCitationOutput(CitationResult):
    resource_uri: str


def project_permission_set(
    *, edit_project: bool, manage_papers: bool, manage_collaborators: bool
) -> ProjectPermissionSet:
    return ProjectPermissionSet(
        edit_project=edit_project,
        manage_papers=manage_papers,
        manage_collaborators=manage_collaborators,
    )
