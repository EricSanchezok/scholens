"""Canonical Agent-facing tools for long-running Scholens research workspaces.

The catalog deliberately excludes internet paper discovery and generative product
features. It exposes the stored-knowledge, ingestion, organization, collaboration,
and annotation surface shared by the in-product Agent and external MCP clients.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.papers.application.contracts.documents import (
    LibrarySummaryResponse,
)
from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentResponse,
    LibraryTagResponse,
)
from app.modules.papers.application.upload_sessions import (
    PreparePaperUploadRequest,
    PreparePaperUploadResponse,
)
from app.modules.projects.application.contracts import ProjectPapersAddedResponse
from app.shared.application import ApplicationExecutor
from app.shared.domain import WorkspacePermission
from app.tooling import workspace_contracts as wc
from app.tooling.catalog import ToolCatalog, ToolProfile
from app.tooling.contracts import (
    DEFAULT_TOOL_OUTPUT_BYTES,
    ToolBehavior,
    ToolConfirmationPolicy,
    ToolDefinition,
    ToolExecutionKind,
    ToolHandler,
    WorkflowToolHandler,
    ToolOutcomeProjector,
)
from app.tooling.citation_projection import (
    project_paper_citation,
    project_resolved_citation,
)
from app.tooling.job_projection import (
    BATCH_INGESTION_OUTPUT_BYTES,
    LIST_JOBS_OUTPUT_BYTES,
    SINGLE_JOB_OUTPUT_BYTES,
    WAIT_FOR_JOBS_OUTPUT_BYTES,
    project_batch_paper_ingestion,
    project_get_job,
    project_list_jobs,
    project_retried_paper_ingestion,
    project_started_paper_ingestion,
    project_wait_for_jobs,
)
from app.tooling.library_paper_projection import project_updated_library_paper
from app.tooling.paper_content_paging import PAPER_CONTENT_OUTPUT_BYTES
from app.tooling.workspace_collection_projection import (
    project_invitation_action,
    project_invitation_list,
    project_library_tag_list,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers
from app.tooling.paper_content_paging import PaperContentSnapshotCache
from pydantic import BaseModel

CONVERSATION_TOOL_PROFILE = "conversation"
MCP_TOOL_PROFILE = "mcp"


def _description(*, use: str, avoid: str, result: str, next_step: str) -> str:
    """Build a consistent decision-oriented description without implementation detail."""
    return (
        f"Use when {use}. Do not use when {avoid}. Returns {result}. Next: {next_step} "
        "When a result includes reader_url, use it as the durable user-facing "
        "Scholens Markdown link; retain DOI, arXiv, and source URLs as provenance only."
    )


def _tool(
    *,
    name: str,
    title: str,
    description: str,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    permission: WorkspacePermission,
    handler: Callable[..., object],
    execution: ToolExecutionKind = ToolExecutionKind.QUERY,
    destructive: bool = False,
    idempotent: bool | None = None,
    open_world: bool = False,
    confirmation: bool = False,
    persist_result: bool = True,
    outcome_projector: ToolOutcomeProjector | None = None,
    max_output_bytes: int = DEFAULT_TOOL_OUTPUT_BYTES,
    subject: str | None = None,
    allow_repeated_calls: bool = False,
    replacement_tool: str | None = None,
) -> ToolDefinition[ApplicationCapabilities]:
    behavior = ToolBehavior(
        read_only=execution in {ToolExecutionKind.QUERY, ToolExecutionKind.ASYNC_QUERY},
        destructive=destructive,
        idempotent=(
            execution in {ToolExecutionKind.QUERY, ToolExecutionKind.ASYNC_QUERY}
            if idempotent is None
            else idempotent
        ),
        open_world=open_world,
    )
    policy = (
        ToolConfirmationPolicy.REQUIRED if confirmation else ToolConfirmationPolicy.NONE
    )
    if execution in {
        ToolExecutionKind.ASYNC_QUERY,
        ToolExecutionKind.WORKFLOW,
    }:
        return ToolDefinition(
            name=name,
            title=title,
            description=description,
            input_model=input_model,
            output_model=output_model,
            execution=execution,
            required_permission=permission,
            behavior=behavior,
            confirmation_policy=policy,
            persist_result=persist_result,
            outcome_projector=outcome_projector,
            max_output_bytes=max_output_bytes,
            workflow_handler=cast(WorkflowToolHandler, handler),
            activity_subject_field=subject,
            allow_repeated_calls=allow_repeated_calls,
            replacement_tool=replacement_tool,
        )
    return ToolDefinition(
        name=name,
        title=title,
        description=description,
        input_model=input_model,
        output_model=output_model,
        execution=execution,
        required_permission=permission,
        behavior=behavior,
        confirmation_policy=policy,
        persist_result=persist_result,
        outcome_projector=outcome_projector,
        max_output_bytes=max_output_bytes,
        handler=cast(ToolHandler[ApplicationCapabilities], handler),
        activity_subject_field=subject,
        allow_repeated_calls=allow_repeated_calls,
        replacement_tool=replacement_tool,
    )


def build_workspace_tool_catalog(
    *,
    ingestion: PaperIngestionWorkflow,
    citations: CitationWorkflow,
    executor: ApplicationExecutor[ApplicationCapabilities] | None = None,
    web_base_url: str = "https://scholens.local",
    cursor_secret: str = "catalog-construction-only",
    paper_content_snapshot_cache: PaperContentSnapshotCache | None = None,
) -> ToolCatalog[ApplicationCapabilities]:
    handlers = WorkspaceToolHandlers(
        executor=cast(ApplicationExecutor[ApplicationCapabilities], executor),
        ingestion=ingestion,
        citations=citations,
        web_base_url=web_base_url,
        cursor_secret=cursor_secret,
        paper_content_snapshot_cache=paper_content_snapshot_cache,
    )
    read = WorkspacePermission.READ
    write = WorkspacePermission.WRITE
    manage = WorkspacePermission.MANAGE
    delete = WorkspacePermission.DELETE
    query = ToolExecutionKind.QUERY
    async_query = ToolExecutionKind.ASYNC_QUERY
    command = ToolExecutionKind.COMMAND
    workflow = ToolExecutionKind.WORKFLOW
    confirmed = wc.ConfirmationAwareAction

    definitions = [
        _tool(
            name="search_scholens_knowledge",
            title="Search Scholens knowledge",
            description=_description(
                use="you need facts or prior work already stored in Scholens",
                avoid="you need to discover papers on the internet",
                result="ranked paper, passage, annotation, comment, and output matches",
                next_step="open the relevant bounded resource before citing or changing it.",
            ),
            input_model=wc.SearchKnowledgeInput,
            output_model=wc.KnowledgeSearchOutput,
            permission=read,
            handler=handlers.search_knowledge,
            execution=query,
            subject="query",
        ),
        _tool(
            name="get_paper",
            title="Get paper metadata",
            description=_description(
                use="you know a Scholens document UUID and need canonical metadata",
                avoid="you need full text or internet discovery",
                result="the paper identity, metadata, processing state, and stable resource link",
                next_step="use get_paper_page for bounded metadata or get_paper_content for evidence.",
            ),
            input_model=wc.DocumentInput,
            output_model=wc.PaperToolResponse,
            permission=read,
            handler=handlers.get_paper,
            replacement_tool="get_paper_page",
        ),
        _tool(
            name="get_paper_page",
            title="Get bounded paper metadata",
            description=_description(
                use="you know a Scholens document UUID and need lossless metadata within a bounded Agent response",
                avoid="the legacy complete get_paper response is known to fit",
                result="one lossless UTF-8 page of canonical metadata JSON",
                next_step="continue with next_cursor until complete, then parse the concatenated JSON.",
            ),
            input_model=wc.PaperMetadataPageInput,
            output_model=wc.PaperJsonDocumentPageOutput,
            permission=read,
            handler=handlers.get_paper_page,
        ),
        _tool(
            name="get_paper_content",
            title="Read bounded paper text",
            description=_description(
                use="you need a bounded range of extracted text from a known paper",
                avoid="you only need metadata or do not know the document UUID",
                result=(
                    "lossless UTF-8-bounded text, numbered compatibility lines, a "
                    "content digest, and an opaque continuation cursor"
                ),
                next_step="continue with next_cursor or cite the returned line range.",
            ),
            input_model=wc.PaperContentInput,
            output_model=wc.PaperContentOutput,
            permission=read,
            handler=handlers.get_paper_content,
            max_output_bytes=PAPER_CONTENT_OUTPUT_BYTES,
        ),
        _tool(
            name="search_paper_content",
            title="Search inside one paper",
            description=_description(
                use="you know the paper UUID and need locations matching text or a pattern",
                avoid="you need cross-paper search",
                result="bounded matching lines with source locators",
                next_step="read surrounding lines with get_paper_content before concluding.",
            ),
            input_model=wc.SearchPaperContentInput,
            output_model=wc.PaperContentSearchOutput,
            permission=read,
            handler=handlers.search_paper_content,
            subject="query",
        ),
        _tool(
            name="get_paper_citation",
            title="Read citation metadata",
            description=_description(
                use="you need stored bibliographic fields and their completeness",
                avoid="you want to contact external metadata providers",
                result=(
                    "bounded citation-field previews, missing required fields, "
                    "content_truncated, and guidance"
                ),
                next_step=(
                    "use get_paper_page for lossless metadata, or call "
                    "resolve_paper_citation when important fields are missing."
                ),
            ),
            input_model=wc.PaperCitationInput,
            output_model=wc.PaperCitationReadOutput,
            permission=read,
            handler=handlers.get_paper_citation,
            outcome_projector=project_paper_citation,
        ),
        _tool(
            name="resolve_paper_citation",
            title="Resolve missing citation metadata",
            description=_description(
                use="stored citation fields are incomplete and external resolution is justified",
                avoid="get_paper_citation reports complete metadata",
                result=(
                    "bounded resolved fields and provider diagnostics with a stable "
                    "paper resource, without a duplicate artifact"
                ),
                next_step=(
                    "use resource_uri or get_paper_page for lossless stored metadata."
                ),
            ),
            input_model=wc.ResolvePaperCitationInput,
            output_model=wc.ResolvedCitationOutput,
            permission=write,
            handler=handlers.resolve_paper_citation,
            execution=workflow,
            open_world=True,
            persist_result=False,
            outcome_projector=project_resolved_citation,
        ),
        _tool(
            name="get_paper_download_url",
            title="Get temporary paper download URL",
            description=_description(
                use="an authorized client needs the original PDF bytes",
                avoid="you only need extracted text or metadata",
                result="a short-lived authenticated download URL and expiry",
                next_step="download promptly and never persist the temporary URL.",
            ),
            input_model=wc.PaperReadInput,
            output_model=wc.PaperDownloadToolResponse,
            permission=read,
            handler=handlers.get_paper_download_url,
        ),
        _tool(
            name="list_projects",
            title="List Projects",
            description=_description(
                use="you need to find an accessible Project or its immutable UUID",
                avoid="a repository already records the exact Project UUID",
                result=(
                    "a cursor-paginated Project summary list with explicit "
                    "content_truncated and guidance fields"
                ),
                next_step=(
                    "continue through next_cursor, use get_project for complete text, "
                    "then store the chosen project_id in AGENTS.md or README."
                ),
            ),
            input_model=wc.ListProjectsInput,
            output_model=wc.ProjectListToolOutput,
            permission=read,
            handler=handlers.list_projects,
        ),
        _tool(
            name="get_project",
            title="Get Project manifest",
            description=_description(
                use="you know a Project UUID and need its durable research binding",
                avoid="you are searching by title",
                result="Project metadata, capabilities, resource URI, web URL, and binding snippet",
                next_step="record the immutable UUID and scholens:// URI in the repository.",
            ),
            input_model=wc.ProjectInput,
            output_model=wc.ProjectToolResponse,
            permission=read,
            handler=handlers.get_project,
        ),
        _tool(
            name="create_project",
            title="Create Project",
            description=_description(
                use="a long-running research effort needs a new shared Scholens boundary",
                avoid="a matching Project already exists",
                result="the new Project manifest and repository-binding snippet",
                next_step="write the returned UUID and resource URI into the repository guidance.",
            ),
            input_model=wc.CreateProjectInput,
            output_model=wc.ProjectToolResponse,
            permission=write,
            handler=handlers.create_project,
            execution=command,
        ),
        _tool(
            name="update_project",
            title="Update Project",
            description=_description(
                use="the Project title or research description must change",
                avoid="you are trying to change ownership or members",
                result="the updated Project manifest",
                next_step="refresh repository prose if it quotes changed human-readable metadata.",
            ),
            input_model=wc.UpdateProjectInput,
            output_model=wc.ProjectToolResponse,
            permission=write,
            handler=handlers.update_project,
            execution=command,
            idempotent=True,
        ),
        _tool(
            name="delete_project",
            title="Delete Project",
            description=_description(
                use="the user explicitly wants to permanently remove the entire Project",
                avoid="the user only wants to leave, remove a paper, or archive local notes",
                result="first an impact preview, then a completion receipt after confirmation",
                next_step="present the preview and retry unchanged only after explicit approval.",
            ),
            input_model=wc.DeleteProjectInput,
            output_model=confirmed,
            permission=delete,
            handler=handlers.delete_project,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="list_project_papers",
            title="List Project papers",
            description=_description(
                use="you need the papers already associated with one Project",
                avoid="you need internet discovery or personal-Library-only papers",
                result=(
                    "a filtered, cursor-paginated paper summary list with explicit "
                    "content_truncated and guidance fields"
                ),
                next_step=(
                    "continue through next_cursor and use get_paper_page for complete "
                    "metadata before downstream paper or annotation work."
                ),
            ),
            input_model=wc.ListProjectPapersInput,
            output_model=wc.ProjectPaperListToolOutput,
            permission=read,
            handler=handlers.list_project_papers,
        ),
        _tool(
            name="add_papers_to_project",
            title="Add papers to Project",
            description=_description(
                use="known accessible Scholens papers should join a Project",
                avoid="the paper has not been ingested yet",
                result="counts of newly added and already-present papers",
                next_step="use list_project_papers to verify the Project manifest.",
            ),
            input_model=wc.AddPapersToProjectInput,
            output_model=ProjectPapersAddedResponse,
            permission=write,
            handler=handlers.add_papers_to_project,
            execution=command,
            idempotent=True,
        ),
        _tool(
            name="remove_paper_from_project",
            title="Remove paper from Project",
            description=_description(
                use="a paper association and its Project-scoped research context must be removed",
                avoid="you want to retain Project annotations or only remove a personal Library entry",
                result="first the exact annotation impact, then a completion receipt",
                next_step="present the preview and retry unchanged only after approval.",
            ),
            input_model=wc.ProjectPaperInput,
            output_model=confirmed,
            permission=delete,
            handler=handlers.remove_paper_from_project,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="list_paper_projects",
            title="List paper Projects",
            description=_description(
                use="you need every accessible Project containing a known paper",
                avoid="you only need the paper's personal Library status",
                result=(
                    "a cursor-paginated Project summary list with explicit "
                    "content_truncated and guidance fields"
                ),
                next_step=(
                    "continue through next_cursor, use get_project for complete text, "
                    "then choose an explicit Project UUID for Project-scoped work."
                ),
            ),
            input_model=wc.ListPaperProjectsInput,
            output_model=wc.ProjectListToolOutput,
            permission=read,
            handler=handlers.list_paper_projects,
        ),
        _tool(
            name="list_project_members",
            title="List Project members",
            description=_description(
                use="you need collaborator identities, roles, or permissions",
                avoid="you need pending invitations",
                result=(
                    "a cursor-paginated list of visible collaborators with bounded "
                    "identity previews, immutable user IDs, and truncation guidance"
                ),
                next_step=(
                    "continue through next_cursor, then use immutable user IDs for "
                    "member or ownership changes."
                ),
            ),
            input_model=wc.ListProjectMembersInput,
            output_model=wc.ProjectMemberListToolOutput,
            permission=read,
            handler=handlers.list_project_members,
        ),
        _tool(
            name="list_project_invitations",
            title="List Project invitations",
            description=_description(
                use="a Project manager needs pending invitation status",
                avoid="you need accepted members",
                result=(
                    "a cursor-paginated list of active invitations with bounded name "
                    "previews and explicit content_truncated guidance"
                ),
                next_step=(
                    "continue through next_cursor, then resend or revoke only the "
                    "specific invitation UUID."
                ),
            ),
            input_model=wc.ListProjectInvitationsInput,
            output_model=wc.ProjectInvitationListOutput,
            permission=manage,
            handler=handlers.list_project_invitations,
            outcome_projector=project_invitation_list,
        ),
        _tool(
            name="create_project_invitation",
            title="Invite Project collaborator",
            description=_description(
                use="the user explicitly wants to email Project access to a person",
                avoid="the person is already a member or email delivery is not intended",
                result=(
                    "an impact preview, then a bounded invitation and delivery-status "
                    "receipt"
                ),
                next_step="confirm before queueing, then inspect delivery status.",
            ),
            input_model=wc.CreateProjectInvitationInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.create_project_invitation,
            execution=workflow,
            open_world=True,
            confirmation=True,
            persist_result=False,
            outcome_projector=project_invitation_action,
        ),
        _tool(
            name="resend_project_invitation",
            title="Resend Project invitation",
            description=_description(
                use="a specific sent or failed invitation must be queued again",
                avoid="permissions or recipient must change",
                result=(
                    "an impact preview, then a bounded refreshed invitation and "
                    "delivery-status receipt"
                ),
                next_step="confirm before queueing and revoke/recreate if recipient details are wrong.",
            ),
            input_model=wc.InvitationInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.resend_project_invitation,
            execution=workflow,
            open_world=True,
            confirmation=True,
            persist_result=False,
            outcome_projector=project_invitation_action,
        ),
        _tool(
            name="revoke_project_invitation",
            title="Revoke Project invitation",
            description=_description(
                use="a pending invitation must stop granting future access",
                avoid="the invitee already accepted and is now a member",
                result="an impact preview, then a revocation receipt",
                next_step="confirm the exact invitation UUID before retrying.",
            ),
            input_model=wc.InvitationInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.revoke_project_invitation,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="accept_project_invitation",
            title="Accept Project invitation",
            description=_description(
                use="the current user wants to join using their own invitation token",
                avoid="the token belongs to someone else or the user has not approved joining",
                result="an impact preview, then the joined Project manifest",
                next_step="confirm, then bind the returned Project UUID where appropriate.",
            ),
            input_model=wc.AcceptProjectInvitationInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.accept_project_invitation,
            execution=command,
            confirmation=True,
        ),
        _tool(
            name="update_project_member",
            title="Update Project member",
            description=_description(
                use="an owner's collaborator permissions must change",
                avoid="ownership should transfer or the member should be removed",
                result=(
                    "an impact preview, then a compact membership receipt containing "
                    "only stable IDs, owner status, and permissions"
                ),
                next_step="confirm the complete replacement permission set.",
            ),
            input_model=wc.UpdateProjectMemberInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.update_project_member,
            execution=command,
            confirmation=True,
        ),
        _tool(
            name="remove_project_member",
            title="Remove Project member",
            description=_description(
                use="an owner explicitly wants to revoke a collaborator's Project access",
                avoid="the current user is leaving or ownership should transfer",
                result="an impact preview, then an access-removal receipt",
                next_step="confirm the immutable user ID before retrying.",
            ),
            input_model=wc.RemoveProjectMemberInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.remove_project_member,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="leave_project",
            title="Leave Project",
            description=_description(
                use="the current non-owner user explicitly wants to lose Project access",
                avoid="the owner has not transferred ownership",
                result="an impact preview, then a departure receipt",
                next_step="remove obsolete repository bindings after confirmation.",
            ),
            input_model=wc.LeaveProjectInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.leave_project,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="transfer_project_ownership",
            title="Transfer Project ownership",
            description=_description(
                use="the owner explicitly wants an existing collaborator to become owner",
                avoid="only collaborator permissions should change",
                result=(
                    "an impact preview, then a compact receipt containing the Project "
                    "and new-owner IDs"
                ),
                next_step="verify the new owner ID before confirmation.",
            ),
            input_model=wc.TransferProjectOwnershipInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.transfer_project_ownership,
            execution=command,
            confirmation=True,
        ),
        _tool(
            name="get_library_summary",
            title="Get Library summary",
            description=_description(
                use="you need counts and attention signals for the personal Library",
                avoid="you need individual paper records",
                result="paper, ingestion, attention, and output counts",
                next_step="list the relevant entity type for details.",
            ),
            input_model=wc.EmptyInput,
            output_model=LibrarySummaryResponse,
            permission=read,
            handler=handlers.get_library_summary,
        ),
        _tool(
            name="list_library_papers",
            title="List Library papers (legacy complete response)",
            description=_description(
                use="an existing client requires the complete legacy Library collection",
                avoid="you need all Project-accessible papers or internet discovery",
                result=(
                    "the complete historical cursor page, including active ingestions; "
                    "unusually large pages can exceed the global MCP output budget"
                ),
                next_step=(
                    "migrate model-facing reads to list_library_paper_summaries, use "
                    "list_jobs for ingestion state, and page lossless metadata with "
                    "get_library_paper_page."
                ),
            ),
            input_model=wc.ListLibraryPapersInput,
            output_model=wc.LibraryPaperListToolOutput,
            permission=read,
            handler=handlers.list_library_papers,
            replacement_tool="list_library_paper_summaries",
        ),
        _tool(
            name="list_library_paper_summaries",
            title="List bounded Library paper summaries",
            description=_description(
                use=(
                    "you need a context-safe page of durable papers explicitly saved "
                    "in the current user's Library"
                ),
                avoid="you need active ingestion state or Project-only papers",
                result=(
                    "bounded cursor-paginated Library paper previews with explicit "
                    "content_truncated and guidance fields"
                ),
                next_step=(
                    "continue through next_cursor, use get_library_paper_page for "
                    "lossless metadata, and use list_jobs for active ingestions."
                ),
            ),
            input_model=wc.ListLibraryPapersInput,
            output_model=wc.LibraryPaperListToolOutput,
            permission=read,
            handler=handlers.list_library_paper_summaries,
        ),
        _tool(
            name="get_library_paper",
            title="Get Library paper (legacy complete response)",
            description=_description(
                use="an existing client requires one complete historical Library entry",
                avoid="the paper is only accessible through a Project",
                result=(
                    "the complete personal entry plus canonical document metadata; "
                    "unusually large records can exceed the global MCP output budget"
                ),
                next_step=(
                    "migrate model-facing reads to get_library_paper_page and continue "
                    "its signed cursor until the lossless JSON is complete."
                ),
            ),
            input_model=wc.DocumentInput,
            output_model=wc.LibraryPaperToolOutput,
            permission=read,
            handler=handlers.get_library_paper,
            replacement_tool="get_library_paper_page",
        ),
        _tool(
            name="get_library_paper_page",
            title="Get bounded Library paper",
            description=_description(
                use=(
                    "you know a personal Library paper UUID and need lossless durable "
                    "Library and canonical document metadata"
                ),
                avoid="you only need a compact list or status preview",
                result="one lossless UTF-8 page of the stable Library paper JSON",
                next_step=(
                    "continue with next_cursor until complete, concatenate content in "
                    "byte order, then parse JSON; use access_url separately for preview."
                ),
            ),
            input_model=wc.LibraryPaperPageInput,
            output_model=wc.PaperJsonDocumentPageOutput,
            permission=read,
            handler=handlers.get_library_paper_page,
        ),
        _tool(
            name="update_library_paper",
            title="Update Library paper",
            description=_description(
                use="personal reading status or metadata overrides must change",
                avoid="canonical shared metadata should change",
                result=(
                    "a bounded updated entry with content_truncated, guidance, and a "
                    "compact mutation receipt"
                ),
                next_step=(
                    "use get_library_paper_page for lossless JSON if the preview was "
                    "truncated."
                ),
            ),
            input_model=wc.UpdateLibraryPaperInput,
            output_model=wc.LibraryPaperToolOutput,
            permission=write,
            handler=handlers.update_library_paper,
            execution=command,
            idempotent=True,
            outcome_projector=project_updated_library_paper,
        ),
        _tool(
            name="remove_library_papers",
            title="Remove Library papers",
            description=_description(
                use="the user explicitly wants one or more personal Library entries removed",
                avoid="Project associations or shared documents should be deleted",
                result="an impact preview, then exact removed document UUIDs",
                next_step="confirm the full UUID set before retrying.",
            ),
            input_model=wc.RemoveLibraryPapersInput,
            output_model=confirmed,
            permission=delete,
            handler=handlers.remove_library_papers,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="collect_project_paper_to_library",
            title="Collect Project paper",
            description=_description(
                use="a Project-accessible paper should also be saved personally",
                avoid="the paper is already in the personal Library",
                result="the collected document UUID",
                next_step="use get_library_paper for personal status and tags.",
            ),
            input_model=wc.CollectProjectPaperInput,
            output_model=wc.ProjectPaperCollectedToolResponse,
            permission=write,
            handler=handlers.collect_project_paper_to_library,
            execution=command,
            idempotent=True,
        ),
        _tool(
            name="share_library_paper",
            title="Share Library paper",
            description=_description(
                use="the user explicitly wants a public read/download link",
                avoid="access should remain limited to Scholens collaborators",
                result="an impact preview, then public token and web URL",
                next_step="confirm public exposure before retrying.",
            ),
            input_model=wc.SharedPaperInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.share_library_paper,
            execution=command,
            open_world=True,
            confirmation=True,
            persist_result=False,
        ),
        _tool(
            name="unshare_library_paper",
            title="Disable Library paper share",
            description=_description(
                use="an existing public link must stop working",
                avoid="a Project collaborator should be removed instead",
                result="an impact preview, then a privacy-change receipt",
                next_step="confirm that existing external links should break.",
            ),
            input_model=wc.SharedPaperInput,
            output_model=confirmed,
            permission=manage,
            handler=handlers.unshare_library_paper,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="collect_shared_paper",
            title="Collect shared paper",
            description=_description(
                use="the current user wants a publicly shared Scholens paper in their Library",
                avoid="the input is a general PDF URL",
                result="the personal Library entry identity and duplicate status",
                next_step="use get_library_paper or add_papers_to_project.",
            ),
            input_model=wc.CollectSharedPaperInput,
            output_model=wc.CollectPublicPaperToolResponse,
            permission=write,
            handler=handlers.collect_shared_paper,
            execution=command,
            idempotent=True,
        ),
        _tool(
            name="list_library_tags",
            title="List Library tags",
            description=_description(
                use="you need the current user's personal tag UUIDs and names",
                avoid="you need Project-wide labels",
                result=(
                    "a cursor-paginated personal tag list with bounded name/color "
                    "previews and explicit content_truncated guidance"
                ),
                next_step=(
                    "continue through next_cursor, then use tag UUIDs in list or "
                    "replace-assignment operations."
                ),
            ),
            input_model=wc.ListLibraryTagsInput,
            output_model=wc.LibraryTagListOutput,
            permission=read,
            handler=handlers.list_library_tags,
            outcome_projector=project_library_tag_list,
        ),
        _tool(
            name="create_library_tag",
            title="Create Library tag",
            description=_description(
                use="a new personal organization label is needed",
                avoid="an equivalent tag already exists",
                result="the created tag UUID and name",
                next_step="assign it with replace_library_paper_tags.",
            ),
            input_model=wc.CreateLibraryTagInput,
            output_model=LibraryTagResponse,
            permission=write,
            handler=handlers.create_library_tag,
            execution=command,
        ),
        _tool(
            name="update_library_tag",
            title="Rename Library tag",
            description=_description(
                use="a personal tag name must change",
                avoid="paper assignments should change",
                result="the renamed tag",
                next_step="continue using the same immutable tag UUID.",
            ),
            input_model=wc.UpdateLibraryTagInput,
            output_model=LibraryTagResponse,
            permission=write,
            handler=handlers.update_library_tag,
            execution=command,
            idempotent=True,
        ),
        _tool(
            name="delete_library_tag",
            title="Delete Library tag",
            description=_description(
                use="the user explicitly wants a personal tag removed everywhere",
                avoid="only selected paper assignments should change",
                result="an impact preview, then a deletion receipt",
                next_step="confirm that every assignment should be removed.",
            ),
            input_model=wc.DeleteLibraryTagInput,
            output_model=confirmed,
            permission=delete,
            handler=handlers.delete_library_tag,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="replace_library_paper_tags",
            title="Replace Library paper tags",
            description=_description(
                use="you know the complete desired tag set for selected Library papers",
                avoid="you intend to add tags without replacing unspecified ones",
                result="the number of updated papers and task status",
                next_step="list Library papers with tag filters to verify.",
            ),
            input_model=wc.ReplaceLibraryPaperTagsInput,
            output_model=LibraryTagAssignmentResponse,
            permission=write,
            handler=handlers.replace_library_paper_tags,
            execution=command,
            idempotent=True,
        ),
        _tool(
            name="ingest_paper",
            title="Ingest known paper",
            description=_description(
                use="you already know a DOI, arXiv ID, PDF URL, or prepared upload ID",
                avoid="you are searching the internet for relevant papers",
                result="a durable ingestion identity and terminal or timed-out job snapshot",
                next_step=(
                    "open the returned paper resource when terminal; otherwise wait for "
                    "the returned job instead of rapidly polling"
                ),
            ),
            input_model=wc.IngestPaperInput,
            output_model=wc.PaperIngestionToolResponse,
            permission=write,
            handler=handlers.ingest_paper,
            execution=workflow,
            open_world=True,
            outcome_projector=project_started_paper_ingestion,
            max_output_bytes=SINGLE_JOB_OUTPUT_BYTES,
        ),
        _tool(
            name="ingest_papers",
            title="Ingest known papers",
            description=_description(
                use="you already know between one and fifty paper sources to import together",
                avoid="you are discovering papers or need different Project destinations per source",
                result=(
                    "ordered per-source acceptance and terminal or timed-out job "
                    "snapshots; source_truncated marks bounded receipt previews"
                ),
                next_step=(
                    "match items by index, inspect rejected items, and wait once for "
                    "only the remaining active jobs"
                ),
            ),
            input_model=wc.IngestPapersInput,
            output_model=wc.BatchPaperIngestionResponse,
            permission=write,
            handler=handlers.ingest_papers,
            execution=workflow,
            open_world=True,
            outcome_projector=project_batch_paper_ingestion,
            max_output_bytes=BATCH_INGESTION_OUTPUT_BYTES,
        ),
        _tool(
            name="retry_paper_ingestion",
            title="Retry paper ingestion",
            description=_description(
                use="a specific failed ingestion job reports a retryable failure",
                avoid="the job is active, completed, or requires different source data",
                result="the restarted ingestion identity and terminal or timed-out job snapshot",
                next_step="wait again only when the returned job remains active.",
            ),
            input_model=wc.RetryPaperIngestionInput,
            output_model=wc.PaperIngestionToolResponse,
            permission=write,
            handler=handlers.retry_paper_ingestion,
            execution=workflow,
            open_world=True,
            outcome_projector=project_retried_paper_ingestion,
            max_output_bytes=SINGLE_JOB_OUTPUT_BYTES,
        ),
        _tool(
            name="cancel_paper_ingestion",
            title="Cancel paper ingestion",
            description=_description(
                use=(
                    "the user explicitly wants a pending or running ingestion stopped, "
                    "or a failed ingestion removed from Library"
                ),
                avoid="the job is completed, merely slow, or the failed source may still be retried",
                result="an impact preview, then a cancellation or removal receipt",
                next_step="confirm the exact job UUID and disclosed cleanup before continuing.",
            ),
            input_model=wc.CancelPaperIngestionInput,
            output_model=confirmed,
            permission=delete,
            handler=handlers.cancel_paper_ingestion,
            execution=workflow,
            destructive=True,
            confirmation=True,
            persist_result=False,
        ),
        _tool(
            name="prepare_paper_upload",
            title="Prepare PDF upload",
            description=_description(
                use="a client can upload known PDF bytes directly to the returned URL",
                avoid="you only have a DOI, arXiv ID, or already reachable PDF URL",
                result="a one-file upload session, required headers, expiry, and upload_id",
                next_step="PUT the exact bytes, then call ingest_paper with source.kind=upload.",
            ),
            input_model=PreparePaperUploadRequest,
            output_model=PreparePaperUploadResponse,
            permission=write,
            handler=handlers.prepare_paper_upload,
            execution=command,
            open_world=True,
            persist_result=False,
        ),
        _tool(
            name="list_jobs",
            title="List jobs",
            description=_description(
                use="you need asynchronous ingestion or research operation status",
                avoid="you already know one job UUID",
                result="a cursor-paginated list of bounded job status snapshots",
                next_step="use get_job for one exact status and actionable failure.",
            ),
            input_model=wc.ListJobsInput,
            output_model=wc.JobListToolOutput,
            permission=read,
            handler=handlers.list_jobs,
            outcome_projector=project_list_jobs,
            max_output_bytes=LIST_JOBS_OUTPUT_BYTES,
        ),
        _tool(
            name="get_job",
            title="Get job",
            description=_description(
                use="you know one job UUID and need to await its exact progress or failure",
                avoid="you are searching across jobs",
                result="terminal status or the latest bounded status snapshot after a wait",
                next_step=(
                    "follow next_action, then use the returned resource identifiers with "
                    "their paper, Project, or research-output tool"
                ),
            ),
            input_model=wc.GetJobInput,
            output_model=wc.WaitableJobResponse,
            permission=read,
            handler=handlers.get_job,
            execution=async_query,
            persist_result=False,
            outcome_projector=project_get_job,
            max_output_bytes=SINGLE_JOB_OUTPUT_BYTES,
        ),
        _tool(
            name="wait_for_jobs",
            title="Wait for jobs",
            description=_description(
                use="one or more known durable jobs remain active after a tool timeout",
                avoid="you do not know exact job UUIDs or all jobs are already terminal",
                result="ordered terminal or timed-out snapshots for every requested job",
                next_step="inspect terminal items or repeat once for only active job IDs.",
            ),
            input_model=wc.WaitForJobsInput,
            output_model=wc.WaitForJobsResponse,
            permission=read,
            handler=handlers.wait_for_jobs,
            execution=async_query,
            persist_result=False,
            allow_repeated_calls=True,
            outcome_projector=project_wait_for_jobs,
            max_output_bytes=WAIT_FOR_JOBS_OUTPUT_BYTES,
        ),
        _tool(
            name="list_annotation_threads",
            title="List annotation threads",
            description=_description(
                use="you need visible discussions anchored to one paper",
                avoid="you need generated research outputs",
                result="bounded thread summaries and stable resource links",
                next_step="open one thread for complete comments before replying.",
            ),
            input_model=wc.ListAnnotationThreadsInput,
            output_model=wc.ThreadListOutput,
            permission=read,
            handler=handlers.list_annotation_threads,
        ),
        _tool(
            name="get_annotation_thread",
            title="Get annotation thread",
            description=_description(
                use="you know a thread UUID and need its quote, anchor, state, and comments",
                avoid="you are searching for a thread",
                result="the complete visible annotation thread",
                next_step="use get_annotation_thread_page when the complete discussion may be large.",
            ),
            input_model=wc.AnnotationThreadInput,
            output_model=wc.ResearchItemToolResponse,
            permission=read,
            handler=handlers.get_annotation_thread,
            replacement_tool="get_annotation_thread_page",
        ),
        _tool(
            name="get_annotation_thread_page",
            title="Get bounded annotation thread",
            description=_description(
                use="you know a thread UUID and need its complete JSON without an unbounded response",
                avoid="you need to search or mutate the thread",
                result="one lossless UTF-8 page of the visible annotation-thread JSON",
                next_step="continue with next_cursor until complete before replying or citing it.",
            ),
            input_model=wc.AnnotationThreadPageInput,
            output_model=wc.PaperJsonDocumentPageOutput,
            permission=read,
            handler=handlers.get_annotation_thread_page,
        ),
        _tool(
            name="annotate_paper",
            title="Annotate paper passage",
            description=_description(
                use="you want to mark an exact passage by quoting paper text",
                avoid="you need to edit or delete an existing annotation thread",
                result="a paintable anchor, stable resource URI, and visual treatment",
                next_step="open the returned resource_uri or add a reply with the thread UUID.",
            ),
            input_model=wc.AnnotatePaperInput,
            output_model=wc.ThreadActionOutput,
            permission=write,
            handler=handlers.annotate_paper,
            execution=command,
        ),
        _tool(
            name="create_annotation_thread",
            title="Create annotation thread",
            description=_description(
                use="you already have a validated pdf_text Reader position",
                avoid="you only have quote text; use annotate_paper instead",
                result="the created thread and stable resource URI",
                next_step="use annotate_paper for future quote-only requests.",
            ),
            input_model=wc.CreateAnnotationThreadInput,
            output_model=wc.ThreadActionOutput,
            permission=write,
            handler=handlers.create_annotation_thread,
            execution=command,
            replacement_tool="annotate_paper",
        ),
        _tool(
            name="update_annotation_thread",
            title="Update annotation thread",
            description=_description(
                use="the thread color or open/resolved status must change",
                avoid="quote text, audience, or comments should change",
                result="the updated thread",
                next_step="read it again when coordinating concurrent collaborators.",
            ),
            input_model=wc.UpdateAnnotationThreadInput,
            output_model=wc.ThreadActionOutput,
            permission=write,
            handler=handlers.update_annotation_thread,
            execution=command,
            idempotent=True,
        ),
        _tool(
            name="delete_annotation_thread",
            title="Delete annotation thread",
            description=_description(
                use="the creator explicitly wants a thread and its discussion removed",
                avoid="resolving the thread is sufficient",
                result="an impact preview, then a deletion receipt",
                next_step="confirm comment loss before retrying.",
            ),
            input_model=wc.DeleteAnnotationThreadInput,
            output_model=confirmed,
            permission=delete,
            handler=handlers.delete_annotation_thread,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="create_annotation_comment",
            title="Reply to annotation thread",
            description=_description(
                use="you need to add substantive discussion to an existing thread",
                avoid="you need a new paper anchor",
                result="the created comment and parent thread resource",
                next_step="use get_annotation_thread to see the full discussion.",
            ),
            input_model=wc.CreateAnnotationCommentInput,
            output_model=wc.CommentActionOutput,
            permission=write,
            handler=handlers.create_annotation_comment,
            execution=command,
        ),
        _tool(
            name="update_annotation_comment",
            title="Update annotation comment",
            description=_description(
                use="the current actor's existing comment text must be replaced",
                avoid="you need to reply or edit another person's comment",
                result="the updated comment and parent thread resource",
                next_step="read the thread to verify discussion context.",
            ),
            input_model=wc.UpdateAnnotationCommentInput,
            output_model=wc.CommentActionOutput,
            permission=write,
            handler=handlers.update_annotation_comment,
            execution=command,
            idempotent=True,
        ),
        _tool(
            name="delete_annotation_comment",
            title="Delete annotation comment",
            description=_description(
                use="the comment author explicitly wants their comment permanently removed",
                avoid="editing the comment is sufficient",
                result="an impact preview, then a deletion receipt",
                next_step="confirm the exact comment preview before retrying.",
            ),
            input_model=wc.DeleteAnnotationCommentInput,
            output_model=confirmed,
            permission=delete,
            handler=handlers.delete_annotation_comment,
            execution=command,
            destructive=True,
            confirmation=True,
        ),
        _tool(
            name="list_research_outputs",
            title="List research outputs",
            description=_description(
                use=(
                    "you need stored annotation threads, citations, audio overviews, "
                    "or data tables"
                ),
                avoid="you want to generate a new output",
                result="legacy complete stored-output items in an explicit scope",
                next_step="migrate to list_research_output_summaries, then open one immutable item UUID.",
            ),
            input_model=wc.ListResearchOutputsInput,
            output_model=wc.ResearchOutputList,
            permission=read,
            handler=handlers.list_research_outputs,
            replacement_tool="list_research_output_summaries",
        ),
        _tool(
            name="list_research_output_summaries",
            title="List research-output summaries",
            description=_description(
                use="you need a bounded catalog of stored annotations, citations, audio overviews, or data tables",
                avoid="you need the complete content of one known output",
                result="cursor-paginated bounded summaries in an explicit scope",
                next_step="open one item with its page tool using the immutable item UUID.",
            ),
            input_model=wc.ListResearchOutputSummariesInput,
            output_model=wc.ResearchOutputSummaryListToolResponse,
            permission=read,
            handler=handlers.list_research_output_summaries,
        ),
        _tool(
            name="get_research_output",
            title="Get research output",
            description=_description(
                use="you know a stored annotation or research-output UUID and need its complete content",
                avoid="you want to generate a new output or need a bounded response",
                result="the complete visible stored output in the legacy shape",
                next_step="migrate to get_research_output_page for lossless bounded reads.",
            ),
            input_model=wc.ResearchOutputInput,
            output_model=wc.ResearchItemToolResponse,
            permission=read,
            handler=handlers.get_research_output,
            replacement_tool="get_research_output_page",
        ),
        _tool(
            name="get_research_output_page",
            title="Get bounded research output",
            description=_description(
                use="you know a stored annotation or research-output UUID and need lossless bounded JSON",
                avoid="you want to generate a new output",
                result="one lossless UTF-8 page of canonical stored-output JSON",
                next_step="continue with next_cursor, concatenate every content fragment, then parse the JSON.",
            ),
            input_model=wc.ResearchOutputPageInput,
            output_model=wc.PaperJsonDocumentPageOutput,
            permission=read,
            handler=handlers.get_research_output_page,
        ),
    ]
    internal_names = frozenset({"wait_for_jobs"})
    shared_names = frozenset(
        definition.name
        for definition in definitions
        if definition.name not in {"prepare_paper_upload", *internal_names}
    )
    return ToolCatalog(
        definitions=definitions,
        require_agent_metadata=True,
        profiles=[
            ToolProfile(
                name=CONVERSATION_TOOL_PROFILE,
                tool_names=shared_names | internal_names,
            ),
            ToolProfile(
                name=MCP_TOOL_PROFILE,
                tool_names=shared_names | {"prepare_paper_upload"},
            ),
        ],
    )


__all__ = [
    "CONVERSATION_TOOL_PROFILE",
    "MCP_TOOL_PROFILE",
    "build_workspace_tool_catalog",
]
