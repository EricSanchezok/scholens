"""Business-tool handlers composed exclusively from Application capabilities."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Callable, Hashable
from datetime import datetime
from typing import cast
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.action_confirmations.application import confirmation_digest
from app.modules.action_confirmations.contracts import ActionImpact
from app.modules.jobs.application.contracts import JobResponse
from app.modules.papers.application.content import PAPER_CONTENT_SEARCH_TIMEOUT_SECONDS
from app.modules.papers.application.contracts.citation import CitationData
from app.modules.papers.application.contracts.documents import (
    LibraryOutputResponse,
    LibraryPaperIngestionResponse,
    LibraryPaperListResponse,
    LibraryPaperUpdateRequest,
)
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperSearchCandidatePage,
    PaperCollection,
    PersonalLibraryPaperCollection,
    PaperSearchRequest,
    SelectedPaperCollection,
)
from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagCreateRequest,
    LibraryTagRenameRequest,
)
from app.modules.papers.application.contracts.uploads import PaperSource
from app.modules.papers.domain.citations import (
    missing_required_fields,
    normalize_style,
)
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectCollaboratorUpdateRequest,
    ProjectCollaboratorResponse,
    ProjectCreateRequest,
    ProjectInvitationCreateRequest,
    ProjectPermissionSet,
    ProjectResponse,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.modules.projects.domain import (
    ProjectAccessFacts,
    ProjectPermission,
    ProjectPermissions,
    require_grant_subset,
    require_member_can_leave,
    require_member_manageable,
    require_permission,
)
from app.modules.research.application.contracts import (
    CreateAnnotationCommentRequest,
    CreateAnnotationThreadRequest,
    ResearchItemResponse,
    ResearchOutputSummary,
    ResearchOutputSummaryListResponse,
    UpdateAnnotationCommentRequest,
    UpdateAnnotationThreadRequest,
)
from app.modules.research.application.positions import ParsedTextPosition
from app.modules.research.application.catalog import (
    ResearchOutputCatalogScope,
    ResearchOutputCatalogSort,
    ResearchOutputPagePosition,
)
from app.modules.research.application.items import (
    AnnotationThreadSummaryKeyset,
    ResearchItemPageAccess,
)
from app.modules.research.application.search import (
    ResearchSearchCandidatePage,
    ResearchSearchPosition,
    ResearchSearchScope,
)
from app.shared.application import ApplicationExecutor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain.enums import (
    ResearchItemKind,
    RoleType,
)
from app.tooling.contracts import (
    DocumentSourceCandidate,
    ToolExecutionContext,
    ToolOutcome,
    ToolOutcomeFinalizer,
    ToolResourceLink,
)
from app.tooling.annotation_mutation_projection import (
    project_annotation_comment,
    project_annotation_thread,
)
from app.tooling.annotation_target_resolution import resolve_annotation_quote
from app.tooling.invocations import tool_arguments_hash
from app.tooling.results import persisted_tool_outcome, restore_tool_outcome
from app.tooling import workspace_contracts as wc
from app.tooling.annotation_summary_projection import ANNOTATION_SUMMARY_MAX_PAGE_ITEMS
from app.tooling.job_waiting import JobWaiter
from app.tooling.json_document_paging import (
    JsonDocumentPager,
    JsonDocumentPagerCache,
    JsonDocumentTooLargeError,
)
from app.tooling.knowledge_search_projection import (
    KNOWLEDGE_SEARCH_MAX_PAGE_ITEMS,
    KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT,
    bounded_knowledge_excerpt,
    bounded_knowledge_source,
    bounded_knowledge_title,
    compact_knowledge_locator,
)
from app.tooling.knowledge_search_paging import (
    AnnotationKnowledgeSourceKey,
    KnowledgeProducer,
    KnowledgeProducerPosition,
    KnowledgeProducerWindow,
    PaperKnowledgeSourceKey,
    RankedKnowledgeCandidate,
    decode_knowledge_cursor,
    encode_knowledge_cursor,
    knowledge_cursor_fingerprint,
    knowledge_rank_score,
)
from app.tooling.library_paper_projection import (
    LIBRARY_PAPER_GUIDANCE,
    LIBRARY_PAPER_LIST_GUIDANCE,
    LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS,
    project_library_paper,
)
from app.tooling.legacy_result_budget import (
    legacy_payload_json_utf8_budget,
    require_legacy_payload_budget,
)
from app.tooling.paper_content_paging import (
    PAPER_CONTENT_SOURCE_UTF8_BYTES,
    PaperContentSearchCapacityError,
    PaperContentSnapshot,
    PaperContentSnapshotCache,
    authorized_paper_content_snapshot,
    json_bounded_prefix,
)
from app.tooling.project_summary_projection import (
    PROJECT_LIST_GUIDANCE,
    PROJECT_LIST_MAX_PAGE_ITEMS,
    PROJECT_MEMBER_LIST_GUIDANCE,
    PROJECT_PAPER_LIST_GUIDANCE,
    PROJECT_PAPER_LIST_MAX_PAGE_ITEMS,
    project_project_detail,
    project_project_member_list,
)
from app.tooling.reader_links import (
    READER_LINK_GUIDANCE,
    build_reader_url,
    normalize_web_base_url,
)
from pydantic import BaseModel, TypeAdapter
from scholens_observability import add_counter

logger = logging.getLogger(__name__)

_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_RESEARCH_OUTPUT_KINDS = (
    ResearchItemKind.ANNOTATION_THREAD,
    ResearchItemKind.CITATION,
    ResearchItemKind.AUDIO_OVERVIEW,
    ResearchItemKind.DATA_TABLE,
)
_GENERATED_OUTPUT_KINDS = _RESEARCH_OUTPUT_KINDS[1:]
_BATCH_INGESTION_CONCURRENCY = 4
_BATCH_ACCEPTANCE_TIMEOUT_SECONDS = 5.0
_PAPER_DISPLAY_TITLE_JSON_BYTES = 512
_LEGACY_TOOL_DURABLE_JSON_UTF8_BYTES = legacy_payload_json_utf8_budget()


class _ResearchRevisionAdvanced(RuntimeError):
    """A Research-item scalar revision raced one bounded hydration."""


class _JsonDocumentRevisionAdvanced(RuntimeError):
    """A lightweight durable-JSON revision raced one bounded hydration."""


def _json(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _JSON_VALUE.validate_python(value)


def _json_object(value: object) -> dict[str, JsonValue]:
    parsed = _json(value)
    if not isinstance(parsed, dict):
        raise TypeError("expected an object result")
    return parsed


def _digest(value: object) -> str:
    return confirmation_digest(value)


def _impact_label(value: str | None, *, max_json_bytes: int = 240) -> str:
    normalized = " ".join((value or "Untitled").split()) or "Untitled"
    bounded = json_bounded_prefix(normalized, max_bytes=max_json_bytes)
    if bounded == normalized:
        return normalized
    bounded = json_bounded_prefix(normalized, max_bytes=max_json_bytes - 3)
    return bounded.rstrip() + "…"


def _bounded_affected_resources(resources: list[str]) -> list[str]:
    if len(resources) <= 100:
        return resources
    return [*resources[:99], f"additional_resources:{len(resources) - 99}"]


def _project_permissions(value: ProjectPermissionSet) -> ProjectPermissions:
    return ProjectPermissions(
        edit_project=value.edit_project,
        manage_papers=value.manage_papers,
        manage_collaborators=value.manage_collaborators,
    )


def _project_access(project: ProjectResponse, *, actor_id: int) -> ProjectAccessFacts:
    return ProjectAccessFacts(
        user_id=actor_id,
        owner_id=project.owner.id,
        permissions=_project_permissions(project.membership.permissions),
    )


def _project_member_receipt(
    *,
    project_id: UUID,
    member: ProjectCollaboratorResponse,
) -> dict[str, JsonValue]:
    return {
        "project_id": str(project_id),
        "user_id": member.user_id,
        "is_owner": member.is_owner,
        "permissions": _json_object(member.permissions),
    }


def _resource_link(uri: str, name: str, description: str) -> ToolResourceLink:
    return ToolResourceLink(
        uri=uri,
        name=json_bounded_prefix(name, max_bytes=512),
        description=json_bounded_prefix(description, max_bytes=1_024),
    )


def _paper_link(document_id: UUID, title: str | None = None) -> ToolResourceLink:
    return _resource_link(
        f"scholens://papers/{document_id}",
        title or f"Paper {document_id}",
        "Canonical Scholens paper metadata. Use reader_url for browser reading and "
        "get_paper_content for bounded text.",
    )


def _project_link(project_id: UUID, title: str | None = None) -> ToolResourceLink:
    return _resource_link(
        f"scholens://projects/{project_id}",
        title or f"Project {project_id}",
        "Bounded Project manifest for restoring a long-running research context.",
    )


def _thread_link(thread_id: UUID) -> ToolResourceLink:
    return _resource_link(
        f"scholens://annotation-threads/{thread_id}",
        f"Annotation thread {thread_id}",
        "Complete annotation thread and discussion visible to the current user.",
    )


def _output_link(item_id: UUID) -> ToolResourceLink:
    return _resource_link(
        f"scholens://research-outputs/{item_id}",
        f"Research output {item_id}",
        "Stored annotation thread, citation, audio overview, or data-table output.",
    )


def _job_resource_links(job: JobResponse) -> tuple[ToolResourceLink, ...]:
    return tuple(
        link
        for link in (
            _paper_link(job.document_id) if job.document_id is not None else None,
            _project_link(job.project_id) if job.project_id is not None else None,
        )
        if link is not None
    )


def _research_item_link(item: ResearchItemResponse) -> ToolResourceLink:
    if item.kind is ResearchItemKind.ANNOTATION_THREAD:
        return _thread_link(item.id)
    return _output_link(item.id)


def _document_source(
    *,
    document_id: UUID,
    excerpt: str,
    title: str | None = None,
    authors: list[str] | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    reader_url: str | None = None,
) -> DocumentSourceCandidate:
    locator: dict[str, JsonValue] = {}
    if start_line is not None:
        locator["start_line"] = start_line
    if end_line is not None:
        locator["end_line"] = end_line
    return DocumentSourceCandidate(
        document_id=document_id,
        excerpt=json_bounded_prefix(excerpt, max_bytes=4_096),
        title=(
            json_bounded_prefix(title, max_bytes=512) if title is not None else None
        ),
        authors=tuple(
            json_bounded_prefix(author, max_bytes=256)
            for author in (authors or ())[:20]
        ),
        locator=locator or None,
        reader_url=reader_url,
    )


class WorkspaceToolHandlers:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        ingestion: PaperIngestionWorkflow,
        citations: CitationWorkflow,
        web_base_url: str,
        cursor_secret: str,
        paper_content_snapshot_cache: PaperContentSnapshotCache | None = None,
    ) -> None:
        self._executor = executor
        self._ingestion = ingestion
        self._job_waiter = JobWaiter(executor=executor)
        self._citations = citations
        self._web_base_url = normalize_web_base_url(web_base_url)
        self._json_document_page_cache = JsonDocumentPagerCache()
        self._research_reader_urls: dict[UUID, str | None] = {}
        self._paper_content_snapshot_cache = (
            paper_content_snapshot_cache
            if paper_content_snapshot_cache is not None
            else PaperContentSnapshotCache()
        )
        self._knowledge_cursors = SignedCursorCodec(
            cursor_secret,
            revision="scholens-knowledge:4",
            error_code="knowledge_search_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )
        self._annotation_cursors = SignedCursorCodec(
            cursor_secret,
            revision="annotation-thread-tools:1",
            error_code="annotation_thread_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )
        self._research_document_cursors = SignedCursorCodec(
            cursor_secret,
            revision="research-output-document:1",
            error_code="research_output_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )
        self._job_cursors = SignedCursorCodec(
            cursor_secret,
            revision="job-tools:1",
            error_code="job_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )
        self._paper_content_cursors = SignedCursorCodec(
            cursor_secret,
            revision="paper-content-tools:2",
            error_code="paper_content_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )
        self._paper_search_cursors = SignedCursorCodec(
            cursor_secret,
            revision="paper-content-search:2",
            error_code="paper_content_search_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )
        self._paper_metadata_cursors = SignedCursorCodec(
            cursor_secret,
            revision="paper-metadata-document:1",
            error_code="paper_metadata_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )
        self._library_paper_cursors = SignedCursorCodec(
            cursor_secret,
            revision="library-paper-document:1",
            error_code="library_paper_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )

    @staticmethod
    def _json_document_page(
        *,
        actor_id: int,
        resource_uri: str,
        pager: JsonDocumentPager,
        cursor: str | None,
        max_utf8_bytes: int,
        cursors: SignedCursorCodec,
        cursor_error_code: str,
        access_url: str | None = None,
        revision: str | None = None,
    ) -> wc.JsonDocumentPageOutput:
        fingerprint_value: dict[str, object] = {
            "actor_id": actor_id,
            "resource_uri": resource_uri,
            "content_sha256": pager.content_sha256,
        }
        if revision is not None:
            fingerprint_value["revision"] = revision
        fingerprint = json.dumps(
            fingerprint_value,
            separators=(",", ":"),
            sort_keys=True,
        )
        start = cursors.decode(cursor=cursor, fingerprint=fingerprint) if cursor else 0
        try:
            page = pager.page(
                start_utf8_byte=start,
                max_utf8_bytes=max_utf8_bytes,
            )
        except ValueError as exc:
            raise AppError(
                code=cursor_error_code,
                message="The content cursor is invalid or stale",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from exc
        next_cursor = (
            None
            if page.complete
            else cursors.encode(
                fingerprint=fingerprint,
                offset=page.end_utf8_byte,
            )
        )
        return wc.JsonDocumentPageOutput(
            resource_uri=resource_uri,
            content=page.content,
            content_sha256=page.content_sha256,
            start_utf8_byte=page.start_utf8_byte,
            end_utf8_byte=page.end_utf8_byte,
            total_utf8_bytes=page.total_utf8_bytes,
            complete=page.complete,
            next_cursor=next_cursor,
            access_url=access_url,
            guidance=(
                "The canonical JSON document is complete. Parse the concatenated "
                "content fragments."
                if page.complete
                else "Call this tool again with next_cursor; concatenate content "
                "fragments in byte-offset order before parsing JSON."
            ),
        )

    def _cached_json_document_pager(
        self,
        *,
        key: Hashable,
        value_factory: Callable[[], object],
    ) -> JsonDocumentPager:
        try:
            return self._json_document_page_cache.get_or_create(
                key=key,
                value_factory=value_factory,
            )
        except JsonDocumentTooLargeError as exc:
            raise AppError(
                code="json_document_paging_limit_exceeded",
                message=(
                    "The canonical JSON document exceeds the supported lossless "
                    "paging limit"
                ),
                kind=FailureKind.PAYLOAD_TOO_LARGE,
                details={
                    "actual_utf8_bytes": exc.actual_utf8_bytes,
                    "maximum_utf8_bytes": exc.maximum_utf8_bytes,
                },
            ) from exc

    def _require_json_page_budget(self, upper_bound: int | None) -> None:
        if upper_bound is None:
            raise RuntimeError("durable_json_size_preflight_missing")
        if upper_bound <= self._json_document_page_cache.max_entry_utf8_bytes:
            return
        raise AppError(
            code="json_document_paging_limit_exceeded",
            message=(
                "The canonical JSON document exceeds the supported lossless "
                "paging limit"
            ),
            kind=FailureKind.PAYLOAD_TOO_LARGE,
            details={
                "durable_json_utf8_upper_bound": upper_bound,
                "maximum_utf8_bytes": (
                    self._json_document_page_cache.max_entry_utf8_bytes
                ),
            },
        )

    @staticmethod
    def _require_legacy_json_budget(
        *,
        upper_bound: int | None,
        tool: str,
        replacement_tool: str,
    ) -> None:
        require_legacy_payload_budget(
            payload_json_utf8_upper_bound=upper_bound,
            tool=tool,
            replacement_tool=replacement_tool,
        )

    def _authorized_paper_content_snapshot(
        self,
        *,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> PaperContentSnapshot:
        return authorized_paper_content_snapshot(
            capability=capabilities.paper_content,
            actor=context.actor,
            document_id=document_id,
            project_id=project_id,
            cache=self._paper_content_snapshot_cache,
        )

    @staticmethod
    def _require_paper(
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> None:
        capabilities.paper_collection_access(
            actor=context.actor,
            collection=(
                SelectedPaperCollection(project_ids=[project_id])
                if project_id is not None
                else context.paper_collection
            ),
            document_id=document_id,
            anchor_document_id=context.anchor_document_id,
        )

    def _reader_url(
        self,
        document_id: UUID | None,
        *,
        project_id: UUID | None = None,
    ) -> str | None:
        if document_id is None:
            return None
        return build_reader_url(
            web_base_url=self._web_base_url,
            document_id=document_id,
            project_id=project_id,
        )

    def _library_paper_list_output(
        self,
        value: object,
        *,
        content_truncated: bool,
        guidance: str,
    ) -> wc.LibraryPaperListToolOutput:
        response = wc.LibraryPaperListToolOutput.model_validate(
            {
                **LibraryPaperListResponse.model_validate(value).model_dump(
                    exclude={"items"}
                ),
                "items": [],
                "content_truncated": content_truncated,
                "guidance": guidance,
            }
        )
        items: list[wc.LibraryPaperListToolEntry] = []
        for item in LibraryPaperListResponse.model_validate(value).items:
            if item.entry_type == "paper":
                items.append(
                    wc.LibraryPaperListPaperToolEntryModel(
                        **item.model_dump(),
                        reader_url=self._reader_url(item.document.document_id),
                    )
                )
            else:
                items.append(
                    wc.LibraryPaperListIngestionToolEntryModel(
                        **item.model_dump(),
                        reader_url=self._reader_url(
                            item.ingestion.document_id,
                            project_id=item.ingestion.project_id,
                        ),
                    )
                )
        return response.model_copy(update={"items": items})

    def _job_with_reader_url(
        self, job: wc.WaitableJobResponse
    ) -> wc.WaitableJobResponse:
        return job.model_copy(
            update={
                "reader_url": self._reader_url(
                    job.document_id,
                    project_id=job.project_id,
                )
            }
        )

    def _research_reader_url(
        self,
        item: ResearchItemResponse,
        *,
        project_id: UUID | None = None,
    ) -> str | None:
        audience_project_id = getattr(item.audience, "project_id", None)
        return self._reader_url(
            item.target_document_id,
            project_id=audience_project_id or project_id,
        )

    def _thread_summary_reader_url(
        self,
        item: object,
        *,
        project_id: UUID | None = None,
    ) -> str | None:
        target_document_id = getattr(item, "target_document_id", None)
        audience = getattr(item, "audience", None)
        audience_project_id = getattr(audience, "project_id", None)
        return self._reader_url(
            target_document_id,
            project_id=audience_project_id or project_id,
        )

    def _research_item_tool_response(
        self,
        item: ResearchItemResponse,
        *,
        project_id: UUID | None = None,
    ) -> wc.ResearchItemToolResponse:
        return wc.ResearchItemToolResponse(
            **item.model_dump(),
            reader_url=self._research_reader_url(item, project_id=project_id),
        )

    def _research_output_tool_entry(
        self,
        entry: LibraryOutputResponse | ResearchItemResponse,
        *,
        project_id: UUID | None = None,
    ) -> wc.LibraryOutputToolResponse | wc.ResearchItemToolResponse:
        if isinstance(entry, LibraryOutputResponse):
            return wc.LibraryOutputToolResponse(
                **entry.model_dump(),
                reader_url=self._research_reader_url(
                    entry.item,
                    project_id=project_id,
                ),
            )
        return self._research_item_tool_response(entry, project_id=project_id)

    def _research_summary_tool_response(
        self,
        summary: ResearchOutputSummary,
        *,
        project_id: UUID | None = None,
    ) -> wc.ResearchOutputSummaryToolResponse:
        audience_project_id = getattr(summary.audience, "project_id", None)
        return wc.ResearchOutputSummaryToolResponse(
            **summary.model_dump(),
            reader_url=self._reader_url(
                summary.target_document_id,
                project_id=audience_project_id or project_id,
            ),
        )

    def _comment_reader_url(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        thread_id: UUID,
    ) -> str | None:
        try:
            thread = capabilities.research_items.get_annotation_thread(
                actor=context.actor,
                thread_id=thread_id,
            )
        except AppError:
            return None
        if not isinstance(thread, ResearchItemResponse):
            return None
        return self._research_reader_url(thread)

    @staticmethod
    def _confirmation(
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: wc.ConfirmedMutationInput,
        *,
        action: str,
        state: object,
        impact: ActionImpact,
    ) -> ToolOutcome | None:
        business_arguments = arguments.model_dump(
            mode="json",
            exclude={"confirmation_token", "idempotency_key"},
        )
        arguments_hash = _digest(business_arguments)
        state_fingerprint = _digest(state)
        if arguments.confirmation_token is None:
            challenge = capabilities.action_confirmations.issue(
                actor=context.actor,
                operation=context.operation,
                action=action,
                arguments_hash=arguments_hash,
                state_fingerprint=state_fingerprint,
                impact=impact,
            )
            return ToolOutcome(payload=_json(challenge))
        capabilities.action_confirmations.consume(
            actor=context.actor,
            operation=context.operation,
            token=arguments.confirmation_token,
            action=action,
            arguments_hash=arguments_hash,
            state_fingerprint=state_fingerprint,
        )
        return None

    async def _atomic_confirmed_workflow(
        self,
        *,
        context: ToolExecutionContext,
        arguments: wc.ConfirmedMutationInput,
        invocation_key: str,
        tool_name: str,
        finalize_outcome: ToolOutcomeFinalizer,
        execute: Callable[[ApplicationCapabilities], ToolOutcome],
    ) -> ToolOutcome:
        """Commit a confirmed DB workflow and its replay receipt atomically.

        Preview calls deliberately do not persist an invocation receipt because
        the confirmation token is the state-changing retry boundary. Confirmed
        calls use the same hash and strict receipt representation as the public
        dispatcher while holding the invocation advisory lock for the complete
        business transaction.
        """
        arguments_hash = tool_arguments_hash(arguments)
        persist_receipt = arguments.confirmation_token is not None

        def transact(capabilities: ApplicationCapabilities) -> ToolOutcome:
            if persist_receipt:
                replay = capabilities.tool_invocations.replay(
                    actor_id=context.actor.id,
                    invocation_key=invocation_key,
                    tool_name=tool_name,
                    arguments_hash=arguments_hash,
                )
                if replay is not None:
                    return finalize_outcome(restore_tool_outcome(replay))
            outcome = finalize_outcome(execute(capabilities))
            if persist_receipt:
                capabilities.tool_invocations.complete(
                    actor_id=context.actor.id,
                    operation_id=context.operation.trace.operation_id,
                    invocation_key=invocation_key,
                    tool_name=tool_name,
                    arguments_hash=arguments_hash,
                    result=persisted_tool_outcome(outcome),
                )
            return outcome

        return await asyncio.to_thread(self._executor.command, transact)

    @staticmethod
    def _completed(
        *,
        action: str,
        affected_resources: list[str],
        result: object | None = None,
        changed: bool = True,
        guidance: str | None = None,
        links: tuple[ToolResourceLink, ...] = (),
    ) -> ToolOutcome:
        bounded_resources = _bounded_affected_resources(affected_resources)
        payload = wc.CompletedAction(
            action=action,
            changed=changed,
            affected_resources=bounded_resources,
            result=_json_object(result) if result is not None else None,
            guidance=guidance,
        )
        action_receipt = payload.model_copy(update={"result": None})
        return ToolOutcome(
            payload=_json(payload),
            action=_json_object(action_receipt),
            resource_links=links,
        )

    def search_knowledge(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.SearchKnowledgeInput.model_validate(arguments)
        fingerprint = knowledge_cursor_fingerprint(
            actor_id=context.actor.id,
            request=parsed,
        )
        cursor_state = decode_knowledge_cursor(
            codec=self._knowledge_cursors,
            cursor=parsed.cursor,
            fingerprint=fingerprint,
        )
        paper_collection: PaperCollection
        if isinstance(parsed.scope, wc.LibraryKnowledgeScope):
            paper_collection = PersonalLibraryPaperCollection()
        elif isinstance(parsed.scope, wc.AllAccessibleKnowledgeScope):
            paper_collection = LibraryPaperCollection()
        elif isinstance(parsed.scope, wc.ProjectKnowledgeScope):
            paper_collection = SelectedPaperCollection(
                project_ids=[parsed.scope.project_id]
            )
        elif isinstance(parsed.scope, wc.PaperKnowledgeScope):
            paper_collection = SelectedPaperCollection(
                project_ids=(
                    [parsed.scope.project_id]
                    if parsed.scope.project_id is not None
                    else []
                ),
                document_ids=[parsed.scope.document_id],
            )
        else:  # pragma: no cover - the discriminated union is exhaustive
            raise AssertionError("unsupported knowledge scope")
        requested_kinds = set(parsed.kinds)

        def include(kind: str) -> bool:
            return not requested_kinds or kind in requested_kinds

        page_limit = min(parsed.limit, KNOWLEDGE_SEARCH_MAX_PAGE_ITEMS)
        windows: list[KnowledgeProducerWindow] = []
        paper_source_pages: dict[PaperKnowledgeSourceKey, PaperSearchCandidatePage] = {}
        annotation_source_pages: dict[
            AnnotationKnowledgeSourceKey,
            ResearchSearchCandidatePage,
        ] = {}
        paper_request = PaperSearchRequest(
            query=parsed.query,
            collection=paper_collection,
            filters=parsed.filters,
            sort=parsed.sort,
            limit=KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT,
        )
        if include("paper"):
            windows.append(
                self._paper_knowledge_window(
                    capabilities=capabilities,
                    context=context,
                    request=paper_request,
                    scope=parsed.scope,
                    producer="paper",
                    position=cursor_state.paper,
                    source_pages=paper_source_pages,
                )
            )
        if include("paper_passage"):
            windows.append(
                self._paper_knowledge_window(
                    capabilities=capabilities,
                    context=context,
                    request=paper_request,
                    scope=parsed.scope,
                    producer="paper_passage",
                    position=cursor_state.paper_passage,
                    source_pages=paper_source_pages,
                )
            )

        if parsed.scope.kind == "project":
            research_scope = ResearchSearchScope.project(parsed.scope.project_id)
            output_scope = ResearchOutputCatalogScope.project(parsed.scope.project_id)
        elif parsed.scope.kind == "paper":
            research_scope = ResearchSearchScope.paper(
                parsed.scope.document_id,
                project_id=parsed.scope.project_id,
            )
            output_scope = ResearchOutputCatalogScope.paper(
                parsed.scope.document_id,
                project_id=parsed.scope.project_id,
            )
        elif parsed.scope.kind == "library":
            research_scope = ResearchSearchScope.personal_library()
            output_scope = ResearchOutputCatalogScope.personal_library()
        else:
            research_scope = ResearchSearchScope.all_accessible()
            output_scope = ResearchOutputCatalogScope.library()
        if include("annotation_thread"):
            windows.append(
                self._annotation_knowledge_window(
                    capabilities=capabilities,
                    context=context,
                    query=parsed.query,
                    scope=research_scope,
                    producer="annotation_thread",
                    position=cursor_state.annotation_thread,
                    source_pages=annotation_source_pages,
                )
            )
        if include("annotation_comment"):
            windows.append(
                self._annotation_knowledge_window(
                    capabilities=capabilities,
                    context=context,
                    query=parsed.query,
                    scope=research_scope,
                    producer="annotation_comment",
                    position=cursor_state.annotation_comment,
                    source_pages=annotation_source_pages,
                )
            )
        if include("research_output"):
            windows.append(
                self._research_output_knowledge_window(
                    capabilities=capabilities,
                    context=context,
                    query=parsed.query,
                    scope=output_scope,
                    position=cursor_state.research_output,
                )
            )

        ranked = sorted(
            (candidate for window in windows for candidate in window.candidates),
            key=lambda candidate: candidate.sort_key(parsed.sort),
        )
        selected = tuple(ranked[:page_limit])
        next_state = cursor_state
        has_more = False
        for window in windows:
            consumed = tuple(
                candidate
                for candidate in selected
                if candidate.producer == window.producer
            )
            if consumed != window.candidates[: len(consumed)]:
                raise RuntimeError(
                    f"knowledge producer {window.producer} violated its merge order"
                )
            if consumed:
                position = consumed[-1].next_position
            elif not window.candidates:
                position = window.scan_position
            else:
                position = cursor_state.position(window.producer)
            producer_has_more = len(consumed) < len(window.candidates) or (
                len(consumed) == len(window.candidates) and window.source_has_more
            )
            has_more = has_more or producer_has_more
            next_state = next_state.advanced(
                window.producer,
                position.model_copy(update={"exhausted": not producer_has_more}),
            )

        result_items = [
            candidate.item.model_copy(
                update={
                    "reader_url": self._reader_url(
                        candidate.item.document_id,
                        project_id=candidate.item.project_id,
                    )
                }
            )
            for candidate in selected
        ]
        result = wc.KnowledgeSearchOutput(
            items=result_items,
            next_cursor=(
                encode_knowledge_cursor(
                    codec=self._knowledge_cursors,
                    state=next_state,
                    fingerprint=fingerprint,
                )
                if has_more
                else None
            ),
            searched_scope=parsed.scope,
        )
        sources = tuple(
            _document_source(
                document_id=item.document_id,
                excerpt=bounded_knowledge_source(item.excerpt),
                title=item.title,
                start_line=cast(int | None, (item.locator or {}).get("start_line")),
                end_line=cast(int | None, (item.locator or {}).get("end_line")),
                reader_url=item.reader_url,
            )
            for item in result.items
            if item.document_id is not None and item.kind in {"paper", "paper_passage"}
        )
        return ToolOutcome(payload=_json(result), sources=sources)

    @staticmethod
    def _empty_knowledge_window(
        producer: KnowledgeProducer,
        position: KnowledgeProducerPosition,
    ) -> KnowledgeProducerWindow:
        return KnowledgeProducerWindow(
            producer=producer,
            candidates=(),
            scan_position=position,
            source_has_more=False,
        )

    def _paper_knowledge_window(
        self,
        *,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        request: PaperSearchRequest,
        scope: wc.KnowledgeScope,
        producer: KnowledgeProducer,
        position: KnowledgeProducerPosition,
        source_pages: dict[PaperKnowledgeSourceKey, PaperSearchCandidatePage],
    ) -> KnowledgeProducerWindow:
        if position.exhausted:
            return self._empty_knowledge_window(producer, position)
        source_key = PaperKnowledgeSourceKey(
            actor_id=context.actor.id,
            request_json=request.model_dump_json(),
            offset=position.offset,
        )
        response = source_pages.get(source_key)
        if response is None:
            response = capabilities.paper_search.candidate_page(
                actor=context.actor,
                request=request,
                offset=position.offset,
            )
            source_pages[source_key] = response
        papers = response.items[:KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT]
        candidates: list[RankedKnowledgeCandidate] = []
        project_id = getattr(scope, "project_id", None)
        for paper_index, paper in enumerate(papers):
            rank = position.offset + paper_index
            paper_title = bounded_knowledge_title(paper.title)
            if producer == "paper":
                candidates.append(
                    RankedKnowledgeCandidate(
                        producer=producer,
                        rank=rank,
                        child_rank=0,
                        sort_time=paper.created_at,
                        item=wc.KnowledgeSearchResult(
                            kind="paper",
                            resource_uri=f"scholens://papers/{paper.document_id}",
                            title=paper_title,
                            excerpt=bounded_knowledge_excerpt(
                                paper.abstract or paper.title or "Stored paper"
                            ),
                            score=knowledge_rank_score(rank=rank, child_rank=0),
                            document_id=paper.document_id,
                            project_id=project_id,
                            entity_id=paper.document_id,
                            updated_at=paper.last_accessed_at,
                        ),
                        next_position=KnowledgeProducerPosition(offset=rank + 1),
                    )
                )
                continue
            child_start = position.child_index if paper_index == 0 else 0
            snippets = paper.snippets[:3]
            for child_index, snippet in enumerate(
                snippets[child_start:],
                start=child_start,
            ):
                next_position = (
                    KnowledgeProducerPosition(
                        offset=rank,
                        child_index=child_index + 1,
                    )
                    if child_index + 1 < len(snippets)
                    else KnowledgeProducerPosition(offset=rank + 1)
                )
                candidates.append(
                    RankedKnowledgeCandidate(
                        producer=producer,
                        rank=rank,
                        child_rank=child_index,
                        sort_time=paper.created_at,
                        item=wc.KnowledgeSearchResult(
                            kind="paper_passage",
                            resource_uri=f"scholens://papers/{paper.document_id}",
                            title=paper_title,
                            excerpt=bounded_knowledge_excerpt(snippet.text),
                            score=knowledge_rank_score(
                                rank=rank,
                                child_rank=child_index,
                            ),
                            document_id=paper.document_id,
                            project_id=project_id,
                            entity_id=paper.document_id,
                            locator={
                                "start_line": snippet.start_line,
                                "end_line": snippet.end_line,
                            },
                            updated_at=paper.last_accessed_at,
                        ),
                        next_position=next_position,
                    )
                )
                if len(candidates) >= KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT:
                    break
            if len(candidates) >= KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT:
                break
        scan_position = KnowledgeProducerPosition(offset=position.offset + len(papers))
        if candidates:
            after = candidates[-1].next_position
            source_has_more = (
                after.child_index > 0
                or after.offset < position.offset + len(papers)
                or after.offset < response.total
            )
        else:
            source_has_more = scan_position.offset < response.total
        return KnowledgeProducerWindow(
            producer=producer,
            candidates=tuple(candidates),
            scan_position=scan_position,
            source_has_more=source_has_more,
        )

    def _annotation_knowledge_window(
        self,
        *,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        query: str,
        scope: ResearchSearchScope,
        producer: KnowledgeProducer,
        position: KnowledgeProducerPosition,
        source_pages: dict[
            AnnotationKnowledgeSourceKey,
            ResearchSearchCandidatePage,
        ],
    ) -> KnowledgeProducerWindow:
        if position.exhausted:
            return self._empty_knowledge_window(producer, position)
        after = self._research_search_position(position)
        source_key = AnnotationKnowledgeSourceKey(
            actor_id=context.actor.id,
            query=query,
            scope_kind=scope.kind.value,
            document_id=scope.document_id,
            project_id=scope.project_id,
            after_created_at=after.created_at if after is not None else None,
            after_item_id=after.item_id if after is not None else None,
            limit=KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT,
        )
        page = source_pages.get(source_key)
        if page is None:
            page = capabilities.research_search.candidate_page(
                actor=context.actor,
                query=query,
                limit=KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT,
                scope=scope,
                after=after,
            )
            source_pages[source_key] = page
        candidates: list[RankedKnowledgeCandidate] = []
        previous = after
        for thread_index, thread in enumerate(page.items):
            rank = position.offset + thread_index
            thread_title = bounded_knowledge_title(thread.document_title)
            current = ResearchSearchPosition(
                created_at=thread.created_at,
                item_id=thread.id,
            )
            if producer == "annotation_thread":
                candidates.append(
                    RankedKnowledgeCandidate(
                        producer=producer,
                        rank=rank,
                        child_rank=0,
                        sort_time=thread.created_at,
                        item=wc.KnowledgeSearchResult(
                            kind="annotation_thread",
                            resource_uri=(f"scholens://annotation-threads/{thread.id}"),
                            title=thread_title,
                            excerpt=bounded_knowledge_excerpt(thread.quote_text),
                            score=knowledge_rank_score(rank=rank, child_rank=0),
                            document_id=thread.document_id,
                            project_id=thread.project_id,
                            entity_id=thread.id,
                            locator=compact_knowledge_locator(thread.position),
                            updated_at=thread.created_at,
                        ),
                        next_position=self._knowledge_position_after_research(
                            offset=rank + 1,
                            child_index=0,
                            after=current,
                        ),
                    )
                )
            else:
                child_start = position.child_index if thread_index == 0 else 0
                comments = thread.matching_comments[:3]
                for child_index, comment in enumerate(
                    comments[child_start:],
                    start=child_start,
                ):
                    next_position = (
                        self._knowledge_position_after_research(
                            offset=rank,
                            child_index=child_index + 1,
                            after=previous,
                        )
                        if child_index + 1 < len(comments)
                        else self._knowledge_position_after_research(
                            offset=rank + 1,
                            child_index=0,
                            after=current,
                        )
                    )
                    candidates.append(
                        RankedKnowledgeCandidate(
                            producer=producer,
                            rank=rank,
                            child_rank=child_index,
                            sort_time=thread.created_at,
                            item=wc.KnowledgeSearchResult(
                                kind="annotation_comment",
                                resource_uri=(
                                    f"scholens://annotation-threads/{thread.id}"
                                ),
                                title=thread_title,
                                excerpt=bounded_knowledge_excerpt(comment.content),
                                score=knowledge_rank_score(
                                    rank=rank,
                                    child_rank=child_index,
                                ),
                                document_id=thread.document_id,
                                project_id=thread.project_id,
                                entity_id=comment.id,
                                locator={"thread_id": str(thread.id)},
                                updated_at=comment.created_at,
                            ),
                            next_position=next_position,
                        )
                    )
                    if len(candidates) >= KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT:
                        break
            previous = current
            if len(candidates) >= KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT:
                break
        scan_position = self._knowledge_position_after_research(
            offset=position.offset + len(page.items),
            child_index=0,
            after=(
                ResearchSearchPosition(
                    created_at=page.items[-1].created_at,
                    item_id=page.items[-1].id,
                )
                if page.items
                else after
            ),
        )
        if candidates:
            candidate_after = candidates[-1].next_position
            source_has_more = (
                candidate_after.child_index > 0
                or candidate_after.offset < position.offset + len(page.items)
                or page.has_more
            )
        else:
            source_has_more = page.has_more
        return KnowledgeProducerWindow(
            producer=producer,
            candidates=tuple(candidates),
            scan_position=scan_position,
            source_has_more=source_has_more,
        )

    def _research_output_knowledge_window(
        self,
        *,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        query: str,
        scope: ResearchOutputCatalogScope,
        position: KnowledgeProducerPosition,
    ) -> KnowledgeProducerWindow:
        producer: KnowledgeProducer = "research_output"
        if position.exhausted:
            return self._empty_knowledge_window(producer, position)
        after = self._research_output_position(position)
        page = capabilities.research_output_catalog.candidate_page(
            actor=context.actor,
            scope=scope,
            query=query,
            kinds=_GENERATED_OUTPUT_KINDS,
            limit=KNOWLEDGE_SEARCH_PRODUCER_CANDIDATE_LIMIT,
            after=after,
        )
        if len(page.items) != len(page.positions):
            raise RuntimeError("research-output candidate positions are incomplete")
        candidates: list[RankedKnowledgeCandidate] = []
        for index, (item, item_position) in enumerate(
            zip(page.items, page.positions, strict=True)
        ):
            rank = position.offset + index
            candidates.append(
                RankedKnowledgeCandidate(
                    producer=producer,
                    rank=rank,
                    child_rank=0,
                    sort_time=item.updated_at,
                    item=wc.KnowledgeSearchResult(
                        kind="research_output",
                        resource_uri=item.resource_uri,
                        title=bounded_knowledge_title(item.title),
                        excerpt=bounded_knowledge_excerpt(item.excerpt),
                        score=knowledge_rank_score(rank=rank, child_rank=0),
                        document_id=item.target_document_id,
                        project_id=getattr(item.audience, "project_id", None),
                        entity_id=item.item_id,
                        updated_at=item.updated_at,
                    ),
                    next_position=KnowledgeProducerPosition(
                        offset=rank + 1,
                        anchor_key=item_position.key,
                        anchor_id=item_position.item_id,
                    ),
                )
            )
        scan_position = candidates[-1].next_position if candidates else position
        return KnowledgeProducerWindow(
            producer=producer,
            candidates=tuple(candidates),
            scan_position=scan_position,
            source_has_more=page.has_more,
        )

    @staticmethod
    def _research_search_position(
        position: KnowledgeProducerPosition,
    ) -> ResearchSearchPosition | None:
        if position.anchor_key is None and position.anchor_id is None:
            return None
        if position.anchor_key is None or position.anchor_id is None:
            raise AppError(
                code="knowledge_search_cursor_invalid",
                message="The knowledge-search cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        try:
            return ResearchSearchPosition(
                created_at=datetime.fromisoformat(position.anchor_key),
                item_id=position.anchor_id,
            )
        except ValueError as error:
            raise AppError(
                code="knowledge_search_cursor_invalid",
                message="The knowledge-search cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from error

    @staticmethod
    def _knowledge_position_after_research(
        *,
        offset: int,
        child_index: int,
        after: ResearchSearchPosition | None,
    ) -> KnowledgeProducerPosition:
        return KnowledgeProducerPosition(
            offset=offset,
            child_index=child_index,
            anchor_key=after.created_at.isoformat() if after is not None else None,
            anchor_id=after.item_id if after is not None else None,
        )

    @staticmethod
    def _research_output_position(
        position: KnowledgeProducerPosition,
    ) -> ResearchOutputPagePosition | None:
        if position.anchor_key is None and position.anchor_id is None:
            return None
        if position.anchor_key is None or position.anchor_id is None:
            raise AppError(
                code="knowledge_search_cursor_invalid",
                message="The knowledge-search cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        return ResearchOutputPagePosition(
            key=position.anchor_key,
            item_id=position.anchor_id,
        )

    def get_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DocumentInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
        )
        access = capabilities.paper_details.authorize_retained_size(
            actor=context.actor,
            document_id=parsed.document_id,
        )
        self._require_legacy_json_budget(
            upper_bound=access.durable_json_utf8_upper_bound,
            tool="get_paper",
            replacement_tool="get_paper_page",
        )
        result = capabilities.paper_details(
            actor=context.actor,
            document_id=parsed.document_id,
        )
        return ToolOutcome(
            payload=_json(
                wc.PaperToolResponse(
                    **result.model_dump(),
                    reader_url=self._reader_url(parsed.document_id),
                )
            ),
            resource_links=(_paper_link(parsed.document_id, result.title),),
        )

    def get_paper_page(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.PaperMetadataPageInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
            project_id=parsed.project_id,
        )
        resource_uri = f"scholens://papers/{parsed.document_id}"
        pager: JsonDocumentPager | None = None
        revision = ""
        for _attempt in range(2):
            access = capabilities.paper_details.authorize_revision(
                actor=context.actor,
                document_id=parsed.document_id,
                project_id=parsed.project_id,
            )
            revision = access.revision

            def durable_value() -> object:
                sized_access = capabilities.paper_details.authorize_retained_size(
                    actor=context.actor,
                    document_id=parsed.document_id,
                    project_id=parsed.project_id,
                )
                if sized_access.revision != access.revision:
                    raise _JsonDocumentRevisionAdvanced
                self._require_json_page_budget(
                    sized_access.durable_json_utf8_upper_bound
                )
                result = capabilities.paper_details(
                    actor=context.actor,
                    document_id=parsed.document_id,
                    project_id=parsed.project_id,
                )
                latest = capabilities.paper_details.authorize_revision(
                    actor=context.actor,
                    document_id=parsed.document_id,
                    project_id=parsed.project_id,
                )
                if (
                    result.updated_at.isoformat() != access.revision
                    or latest.revision != access.revision
                ):
                    raise _JsonDocumentRevisionAdvanced
                return result

            try:
                pager = self._cached_json_document_pager(
                    key=(
                        context.actor.id,
                        resource_uri,
                        str(access.document_id),
                        str(parsed.project_id)
                        if parsed.project_id is not None
                        else None,
                        revision,
                    ),
                    value_factory=durable_value,
                )
                break
            except _JsonDocumentRevisionAdvanced:
                continue
        if pager is None:
            raise AppError(
                code="paper_metadata_cursor_invalid",
                message="The paper metadata changed while the page was prepared",
                kind=FailureKind.CONFLICT,
            )
        page = self._json_document_page(
            actor_id=context.actor.id,
            resource_uri=resource_uri,
            pager=pager,
            cursor=parsed.cursor,
            max_utf8_bytes=parsed.max_utf8_bytes,
            cursors=self._paper_metadata_cursors,
            cursor_error_code="paper_metadata_cursor_invalid",
            revision=revision,
        )
        return ToolOutcome(
            payload=_json(
                wc.PaperJsonDocumentPageOutput(
                    **page.model_dump(),
                    reader_url=self._reader_url(
                        parsed.document_id,
                        project_id=parsed.project_id,
                    ),
                )
            ),
            resource_links=(_paper_link(parsed.document_id),),
        )

    def get_paper_content(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.PaperContentInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
            project_id=parsed.project_id,
        )
        snapshot = self._authorized_paper_content_snapshot(
            capabilities=capabilities,
            context=context,
            document_id=parsed.document_id,
            project_id=parsed.project_id,
        )
        raw_content = snapshot.pager.raw_content
        pager = snapshot.pager
        content_sha = snapshot.content_sha256
        fingerprint = json.dumps(
            {
                "actor_id": context.actor.id,
                "document_id": str(parsed.document_id),
                "project_id": (
                    str(parsed.project_id) if parsed.project_id is not None else None
                ),
                "content_revision": snapshot.revision,
                "content_sha256": content_sha,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        if parsed.cursor is not None and parsed.start_line != 1:
            raise AppError(
                code="paper_content_cursor_conflict",
                message="start_line cannot be combined with a continuation cursor",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        if parsed.cursor is not None:
            try:
                raw_offset, raw_start_line = self._paper_content_cursors.decode_keyset(
                    cursor=parsed.cursor,
                    fingerprint=fingerprint,
                    arity=2,
                )
                offset = int(raw_offset)
                start_line = int(raw_start_line)
                if offset < 0 or start_line < 1:
                    raise ValueError("negative paper-content cursor value")
            except (TypeError, ValueError) as exc:
                raise AppError(
                    code="paper_content_cursor_invalid",
                    message="The paper content cursor is invalid or expired",
                    kind=FailureKind.INVALID_ARGUMENT,
                ) from exc
        elif raw_content:
            try:
                offset = pager.offset_for_line(parsed.start_line)
                start_line = parsed.start_line
            except ValueError as exc:
                raise AppError(
                    code="paper_content_start_invalid",
                    message="start_line is after the end of the extracted paper text",
                    kind=FailureKind.INVALID_ARGUMENT,
                    details={"total_lines": pager.total_lines},
                ) from exc
        elif parsed.start_line == 1:
            offset = 0
            start_line = 1
        else:
            raise AppError(
                code="paper_content_start_invalid",
                message="start_line is after the end of the extracted paper text",
                kind=FailureKind.INVALID_ARGUMENT,
                details={"total_lines": 0},
            )
        try:
            page = pager.page(
                offset=offset,
                max_lines=parsed.max_lines,
                max_utf8_bytes=parsed.max_utf8_bytes,
                start_line=start_line,
            )
        except ValueError as exc:
            raise AppError(
                code="paper_content_cursor_invalid",
                message="The paper content cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from exc

        selected = page.content.splitlines()
        numbered = [
            f"{page.start_line + line_offset}: {line}"
            for line_offset, line in enumerate(selected)
        ]
        next_cursor = (
            self._paper_content_cursors.encode_keyset(
                fingerprint=fingerprint,
                values=(
                    str(page.next_offset),
                    str(page.next_start_line or page.end_line),
                ),
            )
            if page.next_offset is not None
            else None
        )
        display_title = (
            json_bounded_prefix(
                snapshot.title,
                max_bytes=_PAPER_DISPLAY_TITLE_JSON_BYTES,
            )
            if snapshot.title is not None
            else None
        )
        result = wc.PaperContentOutput(
            document_id=parsed.document_id,
            title=display_title,
            title_truncated=display_title != snapshot.title,
            start_line=page.start_line,
            end_line=page.end_line,
            total_lines=page.total_lines,
            lines=numbered,
            next_start_line=page.next_start_line,
            content_sha256=content_sha,
            content=page.content,
            content_utf8_bytes=len(page.content.encode("utf-8")),
            start_offset=page.start_offset,
            end_offset=page.end_offset,
            starts_mid_line=page.starts_mid_line,
            ends_mid_line=page.ends_mid_line,
            next_cursor=next_cursor,
            truncated=next_cursor is not None,
            reader_url=self._reader_url(
                parsed.document_id,
                project_id=parsed.project_id,
            ),
            guidance=(
                "Continue with next_cursor until it is null. next_start_line is "
                "provided only when the page ends exactly at a line boundary. "
                f"{READER_LINK_GUIDANCE}"
            ),
        )
        return ToolOutcome(
            payload=_json(result),
            sources=(
                _document_source(
                    document_id=parsed.document_id,
                    excerpt=json_bounded_prefix(
                        page.content,
                        max_bytes=PAPER_CONTENT_SOURCE_UTF8_BYTES,
                    ),
                    title=snapshot.title,
                    start_line=page.start_line,
                    end_line=page.end_line,
                    reader_url=self._reader_url(
                        parsed.document_id,
                        project_id=parsed.project_id,
                    ),
                ),
            )
            if page.content
            else (),
            resource_links=(_paper_link(parsed.document_id, snapshot.title),),
        )

    def search_paper_content(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.SearchPaperContentInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
            project_id=parsed.project_id,
        )
        snapshot = self._authorized_paper_content_snapshot(
            capabilities=capabilities,
            context=context,
            document_id=parsed.document_id,
            project_id=parsed.project_id,
        )
        fingerprint = json.dumps(
            {
                "actor_id": context.actor.id,
                "document_id": str(parsed.document_id),
                "project_id": (
                    str(parsed.project_id) if parsed.project_id is not None else None
                ),
                "content_revision": snapshot.revision,
                "query": parsed.query,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        expected_digest: str | None = None
        start_offset = 0
        start_line = 1
        previous_matches = 0
        if parsed.cursor is not None:
            try:
                expected_digest, raw_offset, raw_line, raw_matches = (
                    self._paper_search_cursors.decode_keyset(
                        cursor=parsed.cursor,
                        fingerprint=fingerprint,
                        arity=4,
                    )
                )
                start_offset = int(raw_offset)
                start_line = int(raw_line)
                previous_matches = int(raw_matches)
                if start_offset < 0 or start_line < 1 or previous_matches < 0:
                    raise ValueError("negative paper search cursor value")
            except (TypeError, ValueError) as exc:
                raise AppError(
                    code="paper_content_search_cursor_invalid",
                    message="The paper-content search cursor is invalid or expired",
                    kind=FailureKind.INVALID_ARGUMENT,
                ) from exc
        try:
            with self._paper_content_snapshot_cache.search_slot(
                timeout_seconds=PAPER_CONTENT_SEARCH_TIMEOUT_SECONDS
            ):
                page = capabilities.paper_content.search_content(
                    content=snapshot.raw_content,
                    content_sha256=snapshot.content_sha256,
                    query=parsed.query,
                    start_offset=start_offset,
                    start_line=start_line,
                    expected_content_sha256=expected_digest,
                    limit=parsed.limit,
                )
        except PaperContentSearchCapacityError as exc:
            raise AppError(
                code="paper_content_search_capacity_exceeded",
                message=(
                    "Paper-content search capacity is currently occupied; retry "
                    "the same request"
                ),
                kind=FailureKind.RATE_LIMITED,
            ) from exc
        next_cursor = (
            self._paper_search_cursors.encode_keyset(
                fingerprint=fingerprint,
                values=(
                    page.content_sha256,
                    str(page.next_offset),
                    str(page.next_line),
                    str(previous_matches + len(page.matches)),
                ),
            )
            if page.next_offset is not None and page.next_line is not None
            else None
        )
        result = wc.PaperContentSearchOutput(
            document_id=parsed.document_id,
            matches=list(page.matches),
            match_count=len(page.matches),
            total_match_count=(
                previous_matches + len(page.matches) if next_cursor is None else None
            ),
            next_cursor=next_cursor,
            truncated=next_cursor is not None,
            reader_url=self._reader_url(
                parsed.document_id,
                project_id=parsed.project_id,
            ),
            guidance=(
                "Continue with next_cursor until total_match_count is present. Match "
                "lines are UTF-8 bounded previews; use get_paper_content with the "
                "returned line number for complete surrounding evidence. "
                f"{READER_LINK_GUIDANCE}"
            ),
        )
        sources: list[DocumentSourceCandidate] = []
        for match in page.matches:
            prefix, separator, excerpt = match.partition(": ")
            line = int(prefix) if separator and prefix.isdigit() else None
            sources.append(
                _document_source(
                    document_id=parsed.document_id,
                    excerpt=excerpt if separator else match,
                    start_line=line,
                    end_line=line,
                    reader_url=self._reader_url(
                        parsed.document_id,
                        project_id=parsed.project_id,
                    ),
                )
            )
        return ToolOutcome(
            payload=_json(result),
            sources=tuple(sources),
            resource_links=(_paper_link(parsed.document_id),),
        )

    def get_paper_citation(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.PaperCitationInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
            project_id=parsed.project_id,
        )
        fields = capabilities.citations.read(
            actor=context.actor,
            document_id=parsed.document_id,
            project_id=parsed.project_id,
        )
        if fields is None:
            raise AppError(
                code="paper_citation_not_found",
                message="Citation metadata could not be read for this paper",
                kind=FailureKind.NOT_FOUND,
            )
        style = normalize_style(parsed.style)
        missing = missing_required_fields(fields, style)
        result: dict[str, JsonValue] = {
            "document_id": str(parsed.document_id),
            "preferred_style": style,
            "data": _json(
                CitationData(
                    document_id=str(parsed.document_id),
                    title=fields.title,
                    authors=fields.authors,
                    publish_date=fields.publish_date,
                    journal=fields.journal,
                    publisher=fields.publisher,
                    doi=fields.doi,
                )
            ),
            "missing_fields": _json(missing),
            "complete": not missing,
            "reader_url": self._reader_url(
                parsed.document_id,
                project_id=parsed.project_id,
            ),
            "guidance": (
                "Use resolve_paper_citation only if required fields are missing; that "
                "workflow may contact metadata providers and persist recovered fields."
                if missing
                else "Use the structured fields to render the requested citation style."
            ),
        }
        return ToolOutcome(
            payload=result,
            resource_links=(_paper_link(parsed.document_id, fields.title),),
        )

    async def resolve_paper_citation(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        parsed = wc.ResolvePaperCitationInput.model_validate(arguments)
        arguments_hash = tool_arguments_hash(parsed)
        replay = await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.tool_invocations.replay(
                actor_id=context.actor.id,
                invocation_key=invocation_key,
                tool_name="resolve_paper_citation",
                arguments_hash=arguments_hash,
            ),
        )
        if replay is not None:
            return finalize_outcome(restore_tool_outcome(replay))
        plan = await asyncio.to_thread(
            self._citations.prepare,
            actor=context.actor,
            operation=context.operation,
            document_id=parsed.document_id,
            style=parsed.style,
            project_id=parsed.project_id,
            paper_collection=context.paper_collection,
            anchor_document_id=context.anchor_document_id,
        )

        def transact(capabilities: ApplicationCapabilities) -> ToolOutcome:
            replay = capabilities.tool_invocations.replay(
                actor_id=context.actor.id,
                invocation_key=invocation_key,
                tool_name="resolve_paper_citation",
                arguments_hash=arguments_hash,
            )
            if replay is not None:
                return finalize_outcome(restore_tool_outcome(replay))
            citation = self._citations.apply_prepared(
                capabilities,
                actor=context.actor,
                operation=context.operation,
                plan=plan,
            )
            payload = cast(
                dict[str, JsonValue],
                citation.model_dump(mode="python"),
            )
            payload["resource_uri"] = f"scholens://papers/{parsed.document_id}"
            payload["reader_url"] = self._reader_url(
                parsed.document_id,
                project_id=parsed.project_id,
            )
            outcome = finalize_outcome(
                ToolOutcome(
                    payload=payload,
                    resource_links=(
                        _paper_link(parsed.document_id, citation.data.title),
                    ),
                )
            )
            capabilities.tool_invocations.complete(
                actor_id=context.actor.id,
                operation_id=context.operation.trace.operation_id,
                invocation_key=invocation_key,
                tool_name="resolve_paper_citation",
                arguments_hash=arguments_hash,
                result=persisted_tool_outcome(outcome),
            )
            return outcome

        return await asyncio.to_thread(self._executor.command, transact)

    def get_paper_download_url(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.PaperReadInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
            project_id=parsed.project_id,
        )
        download = capabilities.paper_download(
            actor=context.actor,
            document_id=parsed.document_id,
            project_id=parsed.project_id,
        )
        return ToolOutcome(
            payload=_json(
                wc.PaperDownloadToolResponse(
                    **download.model_dump(),
                    reader_url=self._reader_url(
                        parsed.document_id,
                        project_id=parsed.project_id,
                    ),
                )
            ),
            resource_links=(_paper_link(parsed.document_id),),
        )

    def list_projects(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListProjectsInput.model_validate(arguments)
        summary = capabilities.projects.summary_list(
            actor=context.actor,
            query=parsed.query,
            sort=parsed.sort,
            cursor=parsed.cursor,
            limit=min(parsed.limit, PROJECT_LIST_MAX_PAGE_ITEMS),
        )
        return ToolOutcome(
            payload=_json(
                wc.ProjectListToolOutput(
                    **summary.value.model_dump(),
                    content_truncated=summary.content_truncated,
                    guidance=PROJECT_LIST_GUIDANCE,
                )
            )
        )

    def _project_response(self, project: object) -> wc.ProjectToolResponse:
        parsed = ProjectResponse.model_validate(project)
        projection = project_project_detail(parsed)
        parsed = projection.value
        resource_uri = f"scholens://projects/{parsed.id}"
        return wc.ProjectToolResponse(
            **parsed.model_dump(),
            resource_uri=resource_uri,
            web_url=f"{self._web_base_url}/projects/{parsed.id}",
            binding_markdown=(
                f"Scholens project: {parsed.title}\n"
                f"Project ID: {parsed.id}\n"
                f"Resource: {resource_uri}"
            ),
            content_truncated=projection.content_truncated,
            guidance=(
                "A historical display value exceeded current Project limits. The "
                "immutable Project UUID and permissions are complete; normalize the "
                "Project title or description with update_project when needed."
                if projection.content_truncated
                else None
            ),
        )

    def get_project(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ProjectInput.model_validate(arguments)
        result = self._project_response(
            capabilities.projects.get(actor=context.actor, project_id=parsed.project_id)
        )
        return ToolOutcome(
            payload=_json(result),
            resource_links=(_project_link(result.id, result.title),),
        )

    def create_project(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.CreateProjectInput.model_validate(arguments)
        project = capabilities.projects.create(
            actor=context.actor,
            operation=context.operation,
            request=ProjectCreateRequest(
                title=parsed.title, description=parsed.description
            ),
        )
        result = self._project_response(project)
        payload = _json_object(result)
        return ToolOutcome(
            payload=payload,
            action={
                "kind": "project_created",
                "project_id": str(result.id),
                "resource_uri": result.resource_uri,
            },
            resource_links=(_project_link(result.id, result.title),),
        )

    def update_project(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.UpdateProjectInput.model_validate(arguments)
        request_data = parsed.model_dump(
            exclude={"project_id", "idempotency_key"}, exclude_unset=True
        )
        project = capabilities.projects.update(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            request=ProjectUpdateRequest.model_validate(request_data),
        )
        result = self._project_response(project)
        return ToolOutcome(
            payload=_json(result),
            action={
                "kind": "project_updated",
                "project_id": str(result.id),
                "resource_uri": result.resource_uri,
            },
            resource_links=(_project_link(result.id, result.title),),
        )

    def delete_project(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DeleteProjectInput.model_validate(arguments)
        plan = capabilities.projects.plan_delete(
            actor=context.actor,
            project_id=parsed.project_id,
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="delete_project",
            state=plan.state,
            impact=ActionImpact(
                title="Delete Project permanently",
                summary=(
                    f"Permanently delete Project "
                    f"'{_impact_label(plan.project_title)}' and its "
                    "Project-scoped research context."
                ),
                consequences=[
                    f"Remove {plan.state.paper_association_count} paper associations.",
                    f"Remove {plan.state.research_output_count} Project research outputs.",
                    (
                        f"Delete {plan.state.annotation_thread_count} annotation "
                        f"threads and {plan.state.annotation_comment_count} comments."
                    ),
                    f"Remove access for {plan.state.collaborator_count} collaborators.",
                    f"Invalidate {plan.state.invitation_count} Project invitations.",
                    (
                        f"Preserve {plan.state.conversation_count} private conversations "
                        "with a deleted-context marker."
                    ),
                    (
                        f"Evaluate orphan cleanup for "
                        f"{plan.state.paper_association_count} documents and "
                        f"{plan.state.storage_object_count} stored output objects."
                    ),
                ],
                affected_resources=[f"project:{parsed.project_id}"],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.projects.delete(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            plan=plan,
        )
        return self._completed(
            action="project_deleted",
            affected_resources=[f"project:{parsed.project_id}"],
        )

    def list_project_papers(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListProjectPapersInput.model_validate(arguments)
        summary = capabilities.projects.document_summaries(
            actor=context.actor,
            project_id=parsed.project_id,
            query=parsed.query,
            sort=parsed.sort,
            cursor=parsed.cursor,
            limit=min(parsed.limit, PROJECT_PAPER_LIST_MAX_PAGE_ITEMS),
        )
        paper_list = summary.value
        paper_items = [
            wc.ProjectPaperToolSummary(
                **item.model_dump(),
                reader_url=self._reader_url(
                    item.document_id,
                    project_id=parsed.project_id,
                ),
            )
            for item in paper_list.items
        ]
        return ToolOutcome(
            payload=_json(
                wc.ProjectPaperListToolOutput(
                    **paper_list.model_dump(exclude={"items"}),
                    items=paper_items,
                    content_truncated=summary.content_truncated,
                    guidance=PROJECT_PAPER_LIST_GUIDANCE,
                )
            ),
            resource_links=(_project_link(parsed.project_id),),
        )

    def add_papers_to_project(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.AddPapersToProjectInput.model_validate(arguments)
        result = capabilities.projects.add_documents(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            request=AddPaperToProjectRequest(document_ids=parsed.document_ids),
        )
        return ToolOutcome(
            payload=_json(result),
            action={
                "kind": "papers_added_to_project",
                "project_id": str(parsed.project_id),
                "result": _json(result),
            },
            resource_links=(_project_link(parsed.project_id),),
        )

    def remove_paper_from_project(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ProjectPaperInput.model_validate(arguments)
        plan = capabilities.projects.plan_remove_document(
            actor=context.actor,
            project_id=parsed.project_id,
            document_id=parsed.document_id,
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="remove_paper_from_project",
            state=plan.state,
            impact=ActionImpact(
                title="Remove paper from Project",
                summary=(
                    f"Remove this paper from '{_impact_label(plan.project_title)}'."
                ),
                consequences=[
                    f"Delete {plan.state.annotation_thread_count} Project annotation "
                    f"threads and {plan.state.annotation_comment_count} comments "
                    "anchored to this paper."
                ],
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"document:{parsed.document_id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.projects.remove_document(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            document_id=parsed.document_id,
        )
        return self._completed(
            action="paper_removed_from_project",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"document:{parsed.document_id}",
            ],
            links=(
                _project_link(parsed.project_id, plan.project_title),
                _paper_link(parsed.document_id),
            ),
        )

    def list_paper_projects(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListPaperProjectsInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
        )
        summary = capabilities.projects.project_summaries_for_document_page(
            actor=context.actor,
            document_id=parsed.document_id,
            cursor=parsed.cursor,
            limit=min(parsed.limit, PROJECT_LIST_MAX_PAGE_ITEMS),
        )
        return ToolOutcome(
            payload=_json(
                wc.ProjectListToolOutput(
                    **summary.value.model_dump(),
                    content_truncated=summary.content_truncated,
                    guidance=PROJECT_LIST_GUIDANCE,
                )
            ),
            resource_links=(_paper_link(parsed.document_id),),
        )

    def list_project_members(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListProjectMembersInput.model_validate(arguments)
        projection = project_project_member_list(
            capabilities.projects.members_page(
                actor=context.actor,
                project_id=parsed.project_id,
                cursor=parsed.cursor,
                limit=parsed.limit,
            )
        )
        return ToolOutcome(
            payload=_json(
                wc.ProjectMemberListToolOutput(
                    **projection.value.model_dump(),
                    content_truncated=projection.content_truncated,
                    guidance=PROJECT_MEMBER_LIST_GUIDANCE,
                )
            ),
            resource_links=(_project_link(parsed.project_id),),
        )

    def list_project_invitations(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListProjectInvitationsInput.model_validate(arguments)
        return ToolOutcome(
            payload=_json(
                capabilities.projects.invitations_page(
                    actor=context.actor,
                    project_id=parsed.project_id,
                    cursor=parsed.cursor,
                    limit=parsed.limit,
                )
            ),
            resource_links=(_project_link(parsed.project_id),),
        )

    def update_project_member(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.UpdateProjectMemberInput.model_validate(arguments)
        project = capabilities.projects.get(
            actor=context.actor, project_id=parsed.project_id
        )
        target = capabilities.projects.member(
            actor=context.actor,
            project_id=parsed.project_id,
            user_id=parsed.user_id,
        )
        access = _project_access(project, actor_id=context.actor.id)
        requested = wc.project_permission_set(
            edit_project=parsed.edit_project,
            manage_papers=parsed.manage_papers,
            manage_collaborators=parsed.manage_collaborators,
        )
        requested_permissions = _project_permissions(requested)
        require_member_manageable(
            access,
            target_user_id=target.user_id,
            target_permissions=_project_permissions(target.permissions),
        )
        require_grant_subset(access, requested_permissions)
        if target.permissions == requested:
            return self._completed(
                action="project_member_updated",
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"user:{parsed.user_id}",
                ],
                result=_project_member_receipt(
                    project_id=parsed.project_id,
                    member=target,
                ),
                changed=False,
                guidance="The Project member already has the requested permissions.",
                links=(_project_link(parsed.project_id, project.title),),
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="update_project_member",
            state={"project": project, "target": target},
            impact=ActionImpact(
                title="Change Project member permissions",
                summary=(
                    f"Change permissions for {_impact_label(str(target.email))} in "
                    f"'{_impact_label(project.title)}'."
                ),
                consequences=[
                    f"Current: {target.permissions.model_dump(mode='json')}",
                    f"Requested: {requested.model_dump(mode='json')}",
                ],
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"user:{parsed.user_id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        result = capabilities.projects.update_member(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            user_id=parsed.user_id,
            request=ProjectCollaboratorUpdateRequest.model_validate(
                requested.model_dump()
            ),
        )
        return self._completed(
            action="project_member_updated",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"user:{parsed.user_id}",
            ],
            result=_project_member_receipt(
                project_id=parsed.project_id,
                member=result,
            ),
            links=(_project_link(parsed.project_id, project.title),),
        )

    def remove_project_member(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.RemoveProjectMemberInput.model_validate(arguments)
        project = capabilities.projects.get(
            actor=context.actor, project_id=parsed.project_id
        )
        target = capabilities.projects.member(
            actor=context.actor,
            project_id=parsed.project_id,
            user_id=parsed.user_id,
        )
        require_member_manageable(
            _project_access(project, actor_id=context.actor.id),
            target_user_id=target.user_id,
            target_permissions=_project_permissions(target.permissions),
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="remove_project_member",
            state={"project": project, "target": target},
            impact=ActionImpact(
                title="Remove Project member",
                summary=(
                    f"Remove {_impact_label(str(target.email))} from "
                    f"'{_impact_label(project.title)}'."
                ),
                consequences=[
                    "The member loses Project access immediately; their personal Library remains unchanged."
                ],
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"user:{parsed.user_id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.projects.remove_member(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            user_id=parsed.user_id,
        )
        return self._completed(
            action="project_member_removed",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"user:{parsed.user_id}",
            ],
            links=(_project_link(parsed.project_id, project.title),),
        )

    def leave_project(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.LeaveProjectInput.model_validate(arguments)
        project = capabilities.projects.get(
            actor=context.actor, project_id=parsed.project_id
        )
        require_member_can_leave(
            user_id=context.actor.id,
            owner_id=project.owner.id,
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="leave_project",
            state=project,
            impact=ActionImpact(
                title="Leave Project",
                summary=(
                    f"Remove the current user from '{_impact_label(project.title)}'."
                ),
                consequences=[
                    "Project papers and shared discussions will no longer be accessible unless separately saved or shared."
                ],
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"user:{context.actor.id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.projects.leave(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
        )
        return self._completed(
            action="project_left",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"user:{context.actor.id}",
            ],
        )

    def transfer_project_ownership(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.TransferProjectOwnershipInput.model_validate(arguments)
        request = ProjectTransferRequest(new_owner_id=parsed.new_owner_id)
        plan = capabilities.projects.plan_transfer(
            actor=context.actor,
            project_id=parsed.project_id,
            request=request,
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="transfer_project_ownership",
            state=plan.state,
            impact=ActionImpact(
                title="Transfer Project ownership",
                summary=(
                    f"Make {_impact_label(plan.state.target_email)} the owner of "
                    f"'{_impact_label(plan.project_title)}'."
                ),
                consequences=[
                    "The current owner becomes a collaborator and loses owner-only control.",
                    "Quota ownership for Project papers and active ingestions moves to the new owner.",
                    (
                        f"The plan covers {plan.quota.state.project_document_count} "
                        "Project papers and "
                        f"{plan.quota.state.active_reservation_count} active "
                        "upload reservations."
                    ),
                ],
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"user:{parsed.new_owner_id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.projects.transfer(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            request=request,
            plan=plan,
        )
        return self._completed(
            action="project_ownership_transferred",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"user:{parsed.new_owner_id}",
            ],
            result={
                "project_id": str(parsed.project_id),
                "new_owner_id": parsed.new_owner_id,
            },
            links=(_project_link(parsed.project_id, plan.project_title),),
        )

    async def create_project_invitation(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        parsed = wc.CreateProjectInvitationInput.model_validate(arguments)
        return await self._atomic_confirmed_workflow(
            context=context,
            arguments=parsed,
            invocation_key=invocation_key,
            tool_name="create_project_invitation",
            finalize_outcome=finalize_outcome,
            execute=lambda capabilities: self._create_project_invitation(
                capabilities,
                context,
                parsed,
            ),
        )

    def _create_project_invitation(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: wc.CreateProjectInvitationInput,
    ) -> ToolOutcome:
        parsed = arguments
        request = ProjectInvitationCreateRequest(
            email=parsed.email,
            edit_project=parsed.edit_project,
            manage_papers=parsed.manage_papers,
            manage_collaborators=parsed.manage_collaborators,
        )
        plan = capabilities.projects.plan_invitation_creation(
            actor=context.actor,
            project_id=parsed.project_id,
            request=request,
        )
        consequences = [
            "Granted permissions after acceptance: "
            f"{request.model_dump(mode='json', exclude={'email'})}"
        ]
        if plan.replaced_invitation_id is not None:
            consequences.append(
                "The existing pending invitation link becomes invalid immediately."
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="create_project_invitation",
            state=plan.state,
            impact=ActionImpact(
                title="Invite Project collaborator",
                summary=(
                    f"Email an invitation to {parsed.email} for "
                    f"'{_impact_label(plan.project_title)}'."
                ),
                consequences=consequences,
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"email:{parsed.email}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        invitation = capabilities.projects.create_invitation(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            request=request,
            plan=plan,
        )
        return self._completed(
            action="project_invitation_created",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"invitation:{invitation.id}",
            ],
            result={
                "invitation": _json(invitation),
                "email_delivery": str(invitation.delivery_status),
            },
            guidance=(
                "Email delivery is queued. Check list_project_invitations for "
                "sent or failed status."
            ),
            links=(_project_link(parsed.project_id, invitation.project_name),),
        )

    async def resend_project_invitation(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        parsed = wc.InvitationInput.model_validate(arguments)
        return await self._atomic_confirmed_workflow(
            context=context,
            arguments=parsed,
            invocation_key=invocation_key,
            tool_name="resend_project_invitation",
            finalize_outcome=finalize_outcome,
            execute=lambda capabilities: self._resend_project_invitation(
                capabilities,
                context,
                parsed,
            ),
        )

    def _resend_project_invitation(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: wc.InvitationInput,
    ) -> ToolOutcome:
        parsed = arguments
        project = capabilities.projects.get(
            actor=context.actor, project_id=parsed.project_id
        )
        access = _project_access(project, actor_id=context.actor.id)
        require_permission(access, ProjectPermission.MANAGE_COLLABORATORS)
        invitation = capabilities.projects.invitation(
            actor=context.actor,
            project_id=parsed.project_id,
            invitation_id=parsed.invitation_id,
        )
        if invitation is None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                kind=FailureKind.NOT_FOUND,
            )
        require_grant_subset(
            access,
            _project_permissions(invitation.permissions),
        )
        if invitation.delivery_status.value == "pending":
            raise AppError(
                code="project_invitation_delivery_pending",
                message="Invitation delivery is already pending",
                kind=FailureKind.CONFLICT,
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="resend_project_invitation",
            state=invitation,
            impact=ActionImpact(
                title="Resend Project invitation",
                summary=(
                    "Invalidate the old token and email a new invitation to "
                    f"{invitation.email} for "
                    f"'{_impact_label(project.title)}'."
                ),
                consequences=["Previously delivered invitation links stop working."],
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"invitation:{parsed.invitation_id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        resent = capabilities.projects.resend_invitation(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            invitation_id=parsed.invitation_id,
        )
        return self._completed(
            action="project_invitation_resent",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"invitation:{resent.id}",
            ],
            result={
                "invitation": _json(resent),
                "email_delivery": str(resent.delivery_status),
            },
            guidance=(
                "Email delivery is queued. Check list_project_invitations for "
                "sent or failed status."
            ),
            links=(_project_link(parsed.project_id, resent.project_name),),
        )

    def revoke_project_invitation(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.InvitationInput.model_validate(arguments)
        project = capabilities.projects.get(
            actor=context.actor, project_id=parsed.project_id
        )
        access = _project_access(project, actor_id=context.actor.id)
        require_permission(access, ProjectPermission.MANAGE_COLLABORATORS)
        invitation = capabilities.projects.invitation(
            actor=context.actor,
            project_id=parsed.project_id,
            invitation_id=parsed.invitation_id,
        )
        if invitation is None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                kind=FailureKind.NOT_FOUND,
            )
        require_grant_subset(
            access,
            _project_permissions(invitation.permissions),
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="revoke_project_invitation",
            state=invitation,
            impact=ActionImpact(
                title="Revoke Project invitation",
                summary=(
                    f"Invalidate the invitation for {invitation.email} to "
                    f"'{_impact_label(project.title)}'."
                ),
                consequences=["The invitation link can no longer be accepted."],
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"invitation:{parsed.invitation_id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.projects.revoke_invitation(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            invitation_id=parsed.invitation_id,
        )
        return self._completed(
            action="project_invitation_revoked",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"invitation:{parsed.invitation_id}",
            ],
            links=(_project_link(parsed.project_id, project.title),),
        )

    def accept_project_invitation(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.AcceptProjectInvitationInput.model_validate(arguments)
        capabilities.projects.validate_invitation_token(
            actor=context.actor,
            raw_token=parsed.token,
        )
        state = {
            "token_hash": hashlib.sha256(parsed.token.encode()).hexdigest(),
            "actor": context.actor.id,
        }
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="accept_project_invitation",
            state=state,
            impact=ActionImpact(
                title="Accept Project invitation",
                summary="Join the Project associated with this invitation as the current Scholens user.",
                consequences=[
                    "The Project becomes visible with the permissions chosen by its inviter."
                ],
                affected_resources=[f"user:{context.actor.id}"],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.projects.accept_invitation(
            actor=context.actor, operation=context.operation, raw_token=parsed.token
        )
        return self._completed(
            action="project_invitation_accepted",
            affected_resources=[f"user:{context.actor.id}"],
            guidance="Call list_projects to obtain the joined Project UUID and manifest.",
        )

    def get_library_summary(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del arguments
        return ToolOutcome(
            payload=_json(capabilities.paper_library.summary(actor=context.actor)),
            resource_links=(
                _resource_link(
                    "scholens://library",
                    "Scholens Library",
                    "Current user's personal Library summary.",
                ),
            ),
        )

    def list_library_papers(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListLibraryPapersInput.model_validate(arguments)
        result = capabilities.paper_library.list(
            actor=context.actor,
            query=parsed.query,
            tag_ids=tuple(parsed.tag_ids),
            sort=parsed.sort,
            cursor=parsed.cursor,
            limit=parsed.limit,
            maximum_retained_bytes=_LEGACY_TOOL_DURABLE_JSON_UTF8_BYTES,
        )
        return ToolOutcome(
            payload=_json(
                self._library_paper_list_output(
                    result,
                    content_truncated=False,
                    guidance=LIBRARY_PAPER_LIST_GUIDANCE,
                )
            ),
            resource_links=(
                _resource_link(
                    "scholens://library",
                    "Scholens Library",
                    "Current user's personal Library summary.",
                ),
            ),
        )

    def list_library_paper_summaries(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListLibraryPapersInput.model_validate(arguments)
        summary = capabilities.paper_library.list_summaries(
            actor=context.actor,
            query=parsed.query,
            tag_ids=tuple(parsed.tag_ids),
            sort=parsed.sort,
            cursor=parsed.cursor,
            limit=min(parsed.limit, LIBRARY_PAPER_LIST_MAX_PAGE_ITEMS),
        )
        return ToolOutcome(
            payload=_json(
                self._library_paper_list_output(
                    summary.value,
                    content_truncated=summary.content_truncated,
                    guidance=LIBRARY_PAPER_LIST_GUIDANCE,
                )
            ),
            resource_links=(
                _resource_link(
                    "scholens://library",
                    "Scholens Library",
                    "Current user's durable personal Library papers.",
                ),
            ),
        )

    def get_library_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DocumentInput.model_validate(arguments)
        access = capabilities.paper_library.authorize_retained_size(
            actor=context.actor,
            document_id=parsed.document_id,
        )
        self._require_legacy_json_budget(
            upper_bound=access.durable_json_utf8_upper_bound,
            tool="get_library_paper",
            replacement_tool="get_library_paper_page",
        )
        result = capabilities.paper_library.get(
            actor=context.actor, document_id=parsed.document_id
        )
        return ToolOutcome(
            payload=_json(
                wc.LibraryPaperToolOutput(
                    **result.model_dump(),
                    reader_url=self._reader_url(result.document.document_id),
                    content_truncated=False,
                    guidance=LIBRARY_PAPER_GUIDANCE,
                )
            ),
            resource_links=(_paper_link(parsed.document_id, result.document.title),),
        )

    def get_library_paper_page(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.LibraryPaperPageInput.model_validate(arguments)
        resource_uri = f"scholens://library/papers/{parsed.document_id}"
        pager: JsonDocumentPager | None = None
        revision = ""
        access_url: str | None = None
        for _attempt in range(2):
            access = capabilities.paper_library.authorize_revision(
                actor=context.actor,
                document_id=parsed.document_id,
            )
            revision = access.revision
            access_url = access.access_url

            def durable_value() -> object:
                sized_access = capabilities.paper_library.authorize_retained_size(
                    actor=context.actor,
                    document_id=parsed.document_id,
                )
                if sized_access.revision != access.revision:
                    raise _JsonDocumentRevisionAdvanced
                self._require_json_page_budget(
                    sized_access.durable_json_utf8_upper_bound
                )
                result = capabilities.paper_library.get(
                    actor=context.actor,
                    document_id=parsed.document_id,
                )
                latest = capabilities.paper_library.authorize_revision(
                    actor=context.actor,
                    document_id=parsed.document_id,
                )
                if latest.revision != access.revision:
                    raise _JsonDocumentRevisionAdvanced
                return result.model_copy(update={"preview_url": None})

            try:
                pager = self._cached_json_document_pager(
                    key=(
                        context.actor.id,
                        resource_uri,
                        str(access.library_entry_id),
                        revision,
                    ),
                    value_factory=durable_value,
                )
                break
            except _JsonDocumentRevisionAdvanced:
                continue
        if pager is None:
            raise AppError(
                code="library_paper_cursor_invalid",
                message="The Library paper changed while the page was prepared",
                kind=FailureKind.CONFLICT,
            )
        page = self._json_document_page(
            actor_id=context.actor.id,
            resource_uri=resource_uri,
            pager=pager,
            cursor=parsed.cursor,
            max_utf8_bytes=parsed.max_utf8_bytes,
            cursors=self._library_paper_cursors,
            cursor_error_code="library_paper_cursor_invalid",
            access_url=access_url,
            revision=revision,
        )
        return ToolOutcome(
            payload=_json(
                wc.PaperJsonDocumentPageOutput(
                    **page.model_dump(),
                    reader_url=self._reader_url(parsed.document_id),
                )
            ),
            resource_links=(_paper_link(parsed.document_id),),
        )

    def update_library_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.UpdateLibraryPaperInput.model_validate(arguments)
        result = capabilities.paper_library.update_summary(
            actor=context.actor,
            operation=context.operation,
            document_id=parsed.document_id,
            request=LibraryPaperUpdateRequest(
                status=parsed.status, metadata_overrides=parsed.metadata_overrides
            ),
        )
        projection = project_library_paper(result.response)
        content_truncated = result.content_truncated or projection.content_truncated
        payload = wc.LibraryPaperToolOutput(
            **projection.value.model_dump(),
            reader_url=self._reader_url(
                projection.value.document.document_id,
            ),
            content_truncated=content_truncated,
            guidance=LIBRARY_PAPER_GUIDANCE,
        )
        return ToolOutcome(
            payload=_json(payload),
            action={
                "kind": "library_paper_updated",
                "library_entry_id": str(projection.value.library_entry_id),
                "document_id": str(projection.value.document.document_id),
                "status": projection.value.status.value,
                "content_truncated": content_truncated,
            },
            resource_links=(
                _paper_link(parsed.document_id, projection.value.document.title),
            ),
        )

    def remove_library_papers(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.RemoveLibraryPapersInput.model_validate(arguments)
        # The published v1 schema has always accepted repeated UUIDs. Preserve
        # that boundary while canonicalizing before state locking, impact
        # calculation, and execution so one paper is never counted twice.
        document_ids = tuple(dict.fromkeys(parsed.document_ids))
        plan = capabilities.paper_library.removal_plan(
            actor=context.actor,
            document_ids=document_ids,
        )
        thread_count = sum(
            item.personal_annotation_thread_count for item in plan.state.items
        )
        comment_count = sum(
            item.personal_annotation_comment_count for item in plan.state.items
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="remove_library_papers",
            state=plan.state,
            impact=ActionImpact(
                title="Remove papers from personal Library",
                summary=f"Remove {len(plan.state.items)} Library entries.",
                consequences=[
                    "Project copies remain available through their Projects.",
                    (
                        f"Delete {thread_count} personal annotation threads and "
                        f"their {comment_count} comments."
                    ),
                    "Unreferenced document storage may be scheduled for deletion.",
                ],
                affected_resources=_bounded_affected_resources(
                    [f"document:{document_id}" for document_id in document_ids]
                ),
            ),
        )
        if challenge is not None:
            return challenge
        result = capabilities.paper_library.remove_many(
            actor=context.actor,
            operation=context.operation,
            document_ids=document_ids,
        )
        return self._completed(
            action="library_papers_removed",
            affected_resources=[
                f"document:{document_id}" for document_id in result.removed_document_ids
            ],
            result=result,
        )

    def collect_project_paper_to_library(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.CollectProjectPaperInput.model_validate(arguments)
        result = capabilities.projects.collect_document(
            actor=context.actor,
            operation=context.operation,
            request=CollectPaperFromProjectRequest(
                source_project_id=parsed.source_project_id,
                document_id=parsed.document_id,
            ),
        )
        return ToolOutcome(
            payload=_json(
                wc.ProjectPaperCollectedToolResponse(
                    **result.model_dump(),
                    reader_url=self._reader_url(
                        result.document_id,
                        project_id=parsed.source_project_id,
                    ),
                )
            ),
            action={"kind": "project_paper_collected", "result": _json(result)},
            resource_links=(
                _paper_link(parsed.document_id),
                _project_link(parsed.source_project_id),
            ),
        )

    def share_library_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.SharedPaperInput.model_validate(arguments)
        plan = capabilities.paper_library.confirmation_plan(
            actor=context.actor, document_id=parsed.document_id
        )
        state = plan.state
        already_public = state.is_public or state.share_token_hash is not None
        consequences = [
            "Anyone with the link can read and download the paper until it is unshared."
        ]
        if already_public:
            consequences.insert(
                0,
                "The current public link stops working immediately and is replaced.",
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="share_library_paper",
            state=state,
            impact=ActionImpact(
                title="Make Library paper publicly accessible",
                summary=(
                    f"Rotate the public link for "
                    f"'{_impact_label(state.display_title)}'."
                    if already_public
                    else f"Create a public link for "
                    f"'{_impact_label(state.display_title)}'."
                ),
                consequences=consequences,
                affected_resources=[f"document:{parsed.document_id}"],
            ),
        )
        if challenge is not None:
            return challenge
        result = capabilities.paper_library.share(
            actor=context.actor,
            operation=context.operation,
            document_id=parsed.document_id,
        )
        return self._completed(
            action="library_paper_shared",
            affected_resources=[f"document:{parsed.document_id}"],
            result={
                "share_token": result.share_token,
                "is_public": result.is_public,
                "web_url": f"{self._web_base_url}/shared/{result.share_token}",
            },
            links=(_paper_link(parsed.document_id, state.display_title),),
        )

    def unshare_library_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.SharedPaperInput.model_validate(arguments)
        plan = capabilities.paper_library.confirmation_plan(
            actor=context.actor, document_id=parsed.document_id
        )
        state = plan.state
        if not state.is_public and state.share_token_hash is None:
            return self._completed(
                action="library_paper_unshared",
                affected_resources=[f"document:{parsed.document_id}"],
                changed=False,
                guidance="The Library paper is already private.",
                links=(_paper_link(parsed.document_id, state.display_title),),
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="unshare_library_paper",
            state=state,
            impact=ActionImpact(
                title="Disable public paper link",
                summary=(f"Make '{_impact_label(state.display_title)}' private again."),
                consequences=["Existing public links stop working immediately."],
                affected_resources=[f"document:{parsed.document_id}"],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.paper_library.unshare(
            actor=context.actor,
            operation=context.operation,
            document_id=parsed.document_id,
        )
        return self._completed(
            action="library_paper_unshared",
            affected_resources=[f"document:{parsed.document_id}"],
            links=(_paper_link(parsed.document_id, state.display_title),),
        )

    def collect_shared_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.CollectSharedPaperInput.model_validate(arguments)
        result = capabilities.paper_library.collect_public(
            actor=context.actor,
            operation=context.operation,
            share_token=parsed.share_token,
        )
        return ToolOutcome(
            payload=_json(
                wc.CollectPublicPaperToolResponse(
                    **result.model_dump(),
                    reader_url=self._reader_url(result.document_id),
                )
            ),
            action={"kind": "shared_paper_collected", "result": _json(result)},
            resource_links=(_paper_link(result.document_id),),
        )

    def list_library_tags(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListLibraryTagsInput.model_validate(arguments)
        return ToolOutcome(
            payload=_json(
                capabilities.library_tags.list_page(
                    actor=context.actor,
                    cursor=parsed.cursor,
                    limit=parsed.limit,
                )
            )
        )

    def create_library_tag(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.CreateLibraryTagInput.model_validate(arguments)
        result = capabilities.library_tags.create(
            actor=context.actor,
            operation=context.operation,
            request=LibraryTagCreateRequest(name=parsed.name),
        )
        return ToolOutcome(
            payload=_json(result),
            action={"kind": "library_tag_created", "tag": _json(result)},
        )

    def update_library_tag(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.UpdateLibraryTagInput.model_validate(arguments)
        result = capabilities.library_tags.rename(
            actor=context.actor,
            operation=context.operation,
            tag_id=parsed.tag_id,
            request=LibraryTagRenameRequest(name=parsed.name),
        )
        return ToolOutcome(
            payload=_json(result),
            action={"kind": "library_tag_updated", "tag": _json(result)},
        )

    def delete_library_tag(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DeleteLibraryTagInput.model_validate(arguments)
        tag = capabilities.library_tags.get(
            actor=context.actor,
            tag_id=parsed.tag_id,
        )
        if tag is None:
            raise AppError(
                code="library_tag_not_found",
                message="Library tag not found",
                kind=FailureKind.NOT_FOUND,
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="delete_library_tag",
            state=tag,
            impact=ActionImpact(
                title="Delete Library tag",
                summary=f"Delete the tag '{_impact_label(tag.name)}'.",
                consequences=[
                    "The tag is removed from every Library paper; papers themselves are unchanged."
                ],
                affected_resources=[f"library_tag:{parsed.tag_id}"],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.library_tags.delete(
            actor=context.actor, operation=context.operation, tag_id=parsed.tag_id
        )
        return self._completed(
            action="library_tag_deleted",
            affected_resources=[f"library_tag:{parsed.tag_id}"],
        )

    def replace_library_paper_tags(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ReplaceLibraryPaperTagsInput.model_validate(arguments)
        result = capabilities.library_tags.replace_assignments(
            actor=context.actor,
            operation=context.operation,
            request=LibraryTagAssignmentRequest(
                document_ids=parsed.document_ids, tag_ids=parsed.tag_ids
            ),
        )
        return ToolOutcome(
            payload=_json(result),
            action={
                "kind": "library_tag_assignments_replaced",
                "result": _json(result),
            },
        )

    async def ingest_paper(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        del finalize_outcome
        parsed = wc.IngestPaperInput.model_validate(arguments)
        idempotency_key = (
            parsed.idempotency_key
            or "tool:" + hashlib.sha256(invocation_key.encode()).hexdigest()
        )
        result = await self._start_paper_ingestion(
            context=context,
            source=parsed.source,
            project_id=parsed.project_id,
            add_to_library=parsed.add_to_library,
            idempotency_key=idempotency_key,
        )
        job = self._job_with_reader_url(
            await self._job_waiter.wait_for_one(
                actor=context.actor,
                job_id=result.id,
                wait_seconds=parsed.wait_seconds,
                deadline=context.observation_deadline(wait_seconds=parsed.wait_seconds),
            )
        )
        document_id = result.document_id or job.document_id
        project_id = result.project_id or job.project_id
        ingestion_payload = result.model_dump()
        if document_id is not None:
            ingestion_payload["document_id"] = document_id
        if project_id is not None:
            ingestion_payload["project_id"] = project_id
        response = wc.PaperIngestionToolResponse.model_validate(
            {
                **ingestion_payload,
                "job": job,
                "reader_url": self._reader_url(
                    document_id,
                    project_id=project_id,
                ),
            }
        )
        links = tuple(
            link
            for link in (
                (_paper_link(document_id) if document_id is not None else None),
                (_project_link(project_id) if project_id is not None else None),
            )
            if link is not None
        )
        return ToolOutcome(
            payload=_json(response),
            action={
                "kind": "paper_ingestion_started",
                "job_id": str(job.id),
                "document_id": (str(document_id) if document_id is not None else None),
                "project_id": (str(project_id) if project_id is not None else None),
                "status": job.status,
            },
            resource_links=links,
        )

    async def _start_paper_ingestion(
        self,
        *,
        context: ToolExecutionContext,
        source: PaperSource,
        project_id: UUID | None,
        add_to_library: bool,
        idempotency_key: str,
    ) -> LibraryPaperIngestionResponse:
        if source.kind == "upload":
            return await self._ingestion.from_upload_session(
                actor=context.actor,
                operation=context.operation,
                upload_id=source.upload_id,
                project_id=project_id,
                add_to_library=add_to_library,
                idempotency_key=idempotency_key,
                ip_address=context.client_ip,
            )
        value = (
            source.doi
            if source.kind == "doi"
            else (source.arxiv_id if source.kind == "arxiv" else source.url)
        )
        return await self._ingestion.from_source(
            actor=context.actor,
            operation=context.operation,
            kind=source.kind,
            value=value,
            project_id=project_id,
            add_to_library=add_to_library,
            idempotency_key=idempotency_key,
            ip_address=context.client_ip,
        )

    async def ingest_papers(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        del finalize_outcome
        parsed = wc.IngestPapersInput.model_validate(arguments)
        batch_key = parsed.idempotency_key or (
            "tool:" + hashlib.sha256(invocation_key.encode()).hexdigest()
        )
        semaphore = asyncio.Semaphore(_BATCH_INGESTION_CONCURRENCY)

        async def accept_one(
            index: int, source: PaperSource
        ) -> tuple[int, PaperSource, LibraryPaperIngestionResponse | None, str | None]:
            source_value = (
                source.doi
                if source.kind == "doi"
                else source.arxiv_id
                if source.kind == "arxiv"
                else source.url
                if source.kind == "url"
                else str(source.upload_id)
            )
            normalized_value = source_value.strip().casefold()
            if source.kind == "arxiv":
                normalized_value = normalized_value.removeprefix("arxiv:").strip("/")
            elif source.kind == "doi":
                normalized_value = normalized_value.removeprefix("doi:").removeprefix(
                    "https://doi.org/"
                )
            source_fingerprint = f"{source.kind}:{normalized_value}"
            child_key = (
                "tool-batch:"
                + hashlib.sha256(
                    f"{batch_key}:{source_fingerprint}".encode()
                ).hexdigest()
            )
            try:
                async with semaphore:
                    ingestion = await self._start_paper_ingestion(
                        context=context,
                        source=source,
                        project_id=parsed.project_id,
                        add_to_library=parsed.add_to_library,
                        idempotency_key=child_key,
                    )
            except AppError as exc:
                return index, source, None, exc.code
            return index, source, ingestion, None

        tasks = [
            asyncio.create_task(accept_one(index, source))
            for index, source in enumerate(parsed.sources)
        ]
        try:
            done, pending = await asyncio.wait(
                tasks,
                timeout=_BATCH_ACCEPTANCE_TIMEOUT_SECONDS,
            )
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        accepted_by_index: dict[
            int, tuple[PaperSource, LibraryPaperIngestionResponse]
        ] = {}
        rejected_by_index: dict[int, tuple[PaperSource, str]] = {
            tasks.index(task): (
                parsed.sources[tasks.index(task)],
                "batch_ingestion_acceptance_timeout",
            )
            for task in pending
        }
        for task in done:
            index, source, ingestion, error_code = task.result()
            if ingestion is None:
                assert error_code is not None
                rejected_by_index[index] = (source, error_code)
            else:
                accepted_by_index[index] = (source, ingestion)

        waited = None
        jobs_by_id: dict[UUID, wc.WaitableJobResponse] = {}
        if accepted_by_index:
            accepted_results = [
                accepted_by_index[index][1] for index in sorted(accepted_by_index)
            ]
            waited = await self._job_waiter.wait_for_many(
                actor=context.actor,
                job_ids=[result.id for result in accepted_results],
                wait_seconds=parsed.wait_seconds,
                deadline=context.observation_deadline(wait_seconds=parsed.wait_seconds),
            )
            jobs_by_id = {
                job.id: self._job_with_reader_url(job) for job in waited.items
            }

        items: list[wc.BatchPaperIngestionItem] = []
        links_by_uri: dict[str, ToolResourceLink] = {}
        for index, source in enumerate(parsed.sources):
            accepted = accepted_by_index.get(index)
            if accepted is None:
                _, error_code = rejected_by_index[index]
                items.append(
                    wc.BatchPaperIngestionItem(
                        index=index,
                        source=source,
                        status="rejected",
                        error_code=error_code,
                    )
                )
                continue
            _, ingestion = accepted
            job = jobs_by_id[ingestion.id]
            items.append(
                wc.BatchPaperIngestionItem(
                    index=index,
                    source=source,
                    status="accepted",
                    ingestion=wc.LibraryPaperIngestionToolResponse.model_validate(
                        {
                            **ingestion.model_dump(),
                            "document_id": ingestion.document_id or job.document_id,
                            "project_id": ingestion.project_id or job.project_id,
                            "reader_url": self._reader_url(
                                ingestion.document_id or job.document_id,
                                project_id=ingestion.project_id or job.project_id,
                            ),
                        }
                    ),
                    job=job,
                )
            )
            if ingestion.document_id is not None:
                link = _paper_link(ingestion.document_id)
                links_by_uri[link.uri] = link
            if ingestion.project_id is not None:
                link = _project_link(ingestion.project_id)
                links_by_uri[link.uri] = link

        accepted_jobs = [item.job for item in items if item.job is not None]
        status_counts = {
            status: sum(job.status == status for job in accepted_jobs)
            for status in ("completed", "failed", "cancelled")
        }
        active = sum(
            job.status not in {"completed", "failed", "cancelled"}
            for job in accepted_jobs
        )
        wait = (
            waited.wait
            if waited is not None
            else wc.JobBatchWaitMetadata(
                outcome="all_terminal",
                requested_seconds=parsed.wait_seconds,
                elapsed_ms=0,
                next_action="inspect_items",
                guidance="No jobs were accepted; inspect each rejected item.",
            )
        )
        response = wc.BatchPaperIngestionResponse(
            items=items,
            summary=wc.BatchPaperIngestionSummary(
                requested=len(items),
                accepted=len(accepted_by_index),
                rejected=len(rejected_by_index),
                active=active,
                completed=status_counts["completed"],
                failed=status_counts["failed"],
                cancelled=status_counts["cancelled"],
            ),
            wait=wait,
        )
        add_counter(
            "scholens.tool.batch_ingestion_items",
            value=len(accepted_by_index),
            attributes={"outcome": "accepted"},
        )
        add_counter(
            "scholens.tool.batch_ingestion_items",
            value=len(rejected_by_index),
            attributes={"outcome": "rejected"},
        )
        return ToolOutcome(
            payload=_json(response),
            action={
                "kind": "paper_ingestions_started",
                "requested": response.summary.requested,
                "accepted": response.summary.accepted,
                "rejected": response.summary.rejected,
                "active": response.summary.active,
                "job_ids": [
                    str(item.job.id) for item in response.items if item.job is not None
                ],
            },
            resource_links=tuple(links_by_uri.values()),
        )

    async def retry_paper_ingestion(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        del finalize_outcome
        parsed = wc.RetryPaperIngestionInput.model_validate(arguments)
        result = await self._ingestion.retry(
            actor=context.actor,
            operation=context.operation,
            job_id=parsed.job_id,
            idempotency_key=parsed.idempotency_key
            or "tool:" + hashlib.sha256(invocation_key.encode()).hexdigest(),
        )
        job = self._job_with_reader_url(
            await self._job_waiter.wait_for_one(
                actor=context.actor,
                job_id=result.id,
                wait_seconds=parsed.wait_seconds,
                deadline=context.observation_deadline(wait_seconds=parsed.wait_seconds),
            )
        )
        document_id = result.document_id or job.document_id
        project_id = result.project_id or job.project_id
        ingestion_payload = result.model_dump()
        if document_id is not None:
            ingestion_payload["document_id"] = document_id
        if project_id is not None:
            ingestion_payload["project_id"] = project_id
        response = wc.PaperIngestionToolResponse.model_validate(
            {
                **ingestion_payload,
                "job": job,
                "reader_url": self._reader_url(
                    document_id,
                    project_id=project_id,
                ),
            }
        )
        return ToolOutcome(
            payload=_json(response),
            action={
                "kind": "paper_ingestion_retried",
                "job_id": str(job.id),
                "document_id": (str(document_id) if document_id is not None else None),
                "project_id": (str(project_id) if project_id is not None else None),
                "status": job.status,
            },
            resource_links=_job_resource_links(job),
        )

    async def cancel_paper_ingestion(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        parsed = wc.CancelPaperIngestionInput.model_validate(arguments)
        arguments_hash = tool_arguments_hash(parsed)
        persist_receipt = parsed.confirmation_token is not None

        def execute(
            capabilities: ApplicationCapabilities,
        ) -> tuple[ToolOutcome, bool]:
            if persist_receipt:
                replay = capabilities.tool_invocations.replay(
                    actor_id=context.actor.id,
                    invocation_key=invocation_key,
                    tool_name="cancel_paper_ingestion",
                    arguments_hash=arguments_hash,
                )
                if replay is not None:
                    return finalize_outcome(restore_tool_outcome(replay)), True

            def finalize_and_complete(outcome: ToolOutcome) -> ToolOutcome:
                finalized = finalize_outcome(outcome)
                if persist_receipt:
                    capabilities.tool_invocations.complete(
                        actor_id=context.actor.id,
                        operation_id=context.operation.trace.operation_id,
                        invocation_key=invocation_key,
                        tool_name="cancel_paper_ingestion",
                        arguments_hash=arguments_hash,
                        result=persisted_tool_outcome(finalized),
                    )
                return finalized

            plan = capabilities.paper_ingestion.plan_cancel(
                actor=context.actor,
                job_id=parsed.job_id,
            )
            state = plan.state
            if state.status == "cancelled" or state.dismissed_at is not None:
                action = (
                    "paper_ingestion_removed"
                    if state.status == "failed"
                    else "paper_ingestion_cancelled"
                )
                return (
                    finalize_and_complete(
                        self._completed(
                            action=action,
                            affected_resources=[f"job:{parsed.job_id}"],
                            changed=False,
                        )
                    ),
                    persist_receipt,
                )
            failed = state.status == "failed"
            consequences = (
                [
                    "Remove the failed ingestion from Library and prevent another retry from its preserved source.",
                    "Keep the durable failed job and error code as immutable audit history.",
                ]
                if failed
                else [
                    "Processing stops and reserved capacity is released after the database cancellation commits."
                ]
            )
            if state.library_membership_id is not None:
                consequences.append(
                    "Remove the personal Library membership created by this ingestion."
                )
            if state.project_membership_id is not None:
                consequences.append(
                    "Remove the Project paper association created by this ingestion."
                )
            if state.document_gc_will_be_evaluated:
                consequences.append(
                    "Evaluate the ingested document for asynchronous orphan cleanup."
                )
            affected_resources = [f"job:{parsed.job_id}"]
            if state.document_id is not None:
                affected_resources.append(f"document:{state.document_id}")
            if state.project_id is not None:
                affected_resources.append(f"project:{state.project_id}")
            challenge = self._confirmation(
                capabilities,
                context,
                parsed,
                action="cancel_paper_ingestion",
                state=state,
                impact=ActionImpact(
                    title=(
                        "Remove failed paper ingestion"
                        if failed
                        else "Cancel paper ingestion"
                    ),
                    summary=(
                        f"Remove failed ingestion job {parsed.job_id} from Library."
                        if failed
                        else f"Stop ingestion job {parsed.job_id}."
                    ),
                    consequences=consequences,
                    affected_resources=affected_resources,
                ),
            )
            if challenge is not None:
                return finalize_and_complete(challenge), False
            changed = capabilities.paper_ingestion.cancel(
                actor=context.actor,
                operation=context.operation,
                job_id=parsed.job_id,
                plan=plan,
            )
            return (
                finalize_and_complete(
                    self._completed(
                        action=(
                            "paper_ingestion_removed"
                            if failed
                            else "paper_ingestion_cancelled"
                        ),
                        affected_resources=affected_resources,
                        changed=changed,
                    )
                ),
                persist_receipt,
            )

        outcome, release_required = await asyncio.to_thread(
            self._executor.command,
            execute,
        )
        if release_required:
            await self._ingestion.release_cancelled(
                actor=context.actor,
                job_id=parsed.job_id,
            )
        return outcome

    def prepare_paper_upload(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        from app.modules.papers.application.upload_sessions import (
            PreparePaperUploadRequest,
        )

        parsed = PreparePaperUploadRequest.model_validate(arguments)
        return ToolOutcome(
            payload=_json(
                capabilities.paper_uploads.prepare(actor=context.actor, request=parsed)
            )
        )

    def list_jobs(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListJobsInput.model_validate(arguments)
        cursor_fingerprint = json.dumps(
            {
                "revision": "job-tools:1",
                "actor_id": context.actor.id,
                "filters": parsed.model_dump(
                    mode="json",
                    exclude={"cursor", "limit"},
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        before_created_at: datetime | None = None
        before_id: UUID | None = None
        if parsed.cursor is not None:
            created_at_value, id_value = self._job_cursors.decode_keyset(
                cursor=parsed.cursor,
                fingerprint=cursor_fingerprint,
                arity=2,
            )
            try:
                before_created_at = datetime.fromisoformat(created_at_value)
                before_id = UUID(id_value)
                if before_created_at.tzinfo is None:
                    raise ValueError("job cursor timestamp requires a timezone")
            except (TypeError, ValueError) as exc:
                raise AppError(
                    code="job_cursor_invalid",
                    message="The Job cursor is invalid or expired",
                    kind=FailureKind.INVALID_ARGUMENT,
                ) from exc
        jobs = capabilities.jobs.list_statuses(
            actor=context.actor,
            project_id=parsed.project_id,
            document_id=parsed.document_id,
            operation=parsed.operation,
            active=parsed.active,
            before_created_at=before_created_at,
            before_id=before_id,
            limit=parsed.limit + 1,
        )
        page = jobs[: parsed.limit]
        status_page = [
            wc.JobToolResponse.model_validate(
                {**job.model_dump(mode="json", exclude={"result"}), "result": None}
            ).model_copy(
                update={
                    "reader_url": self._reader_url(
                        job.document_id,
                        project_id=job.project_id,
                    )
                }
            )
            for job in page
        ]
        next_cursor = (
            self._job_cursors.encode_keyset(
                fingerprint=cursor_fingerprint,
                values=(page[-1].created_at.isoformat(), str(page[-1].id)),
            )
            if len(jobs) > parsed.limit and page
            else None
        )
        return ToolOutcome(
            payload=_json(
                wc.JobListToolOutput(
                    items=status_page,
                    next_cursor=next_cursor,
                )
            )
        )

    async def get_job(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        del invocation_key, finalize_outcome
        parsed = wc.GetJobInput.model_validate(arguments)
        job = self._job_with_reader_url(
            await self._job_waiter.wait_for_one(
                actor=context.actor,
                job_id=parsed.job_id,
                wait_seconds=parsed.wait_seconds,
                deadline=context.observation_deadline(wait_seconds=parsed.wait_seconds),
            )
        )
        return ToolOutcome(
            payload=_json(job),
            resource_links=_job_resource_links(job),
        )

    async def wait_for_jobs(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
        finalize_outcome: ToolOutcomeFinalizer,
    ) -> ToolOutcome:
        del invocation_key, finalize_outcome
        parsed = wc.WaitForJobsInput.model_validate(arguments)
        response = await self._job_waiter.wait_for_many(
            actor=context.actor,
            job_ids=parsed.job_ids,
            wait_seconds=parsed.wait_seconds,
            deadline=context.observation_deadline(wait_seconds=parsed.wait_seconds),
        )
        response = response.model_copy(
            update={"items": [self._job_with_reader_url(job) for job in response.items]}
        )
        links_by_uri = {
            link.uri: link
            for job in response.items
            for link in _job_resource_links(job)
        }
        return ToolOutcome(
            payload=_json(response),
            resource_links=tuple(links_by_uri.values()),
        )

    def list_annotation_threads(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListAnnotationThreadsInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
            project_id=parsed.project_id,
        )
        fingerprint = json.dumps(
            {
                "actor_id": context.actor.id,
                "filters": parsed.model_dump(
                    mode="json",
                    exclude={"cursor", "limit"},
                ),
                "order": "annotation-source-position-v1",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        after: AnnotationThreadSummaryKeyset | None = None
        if parsed.cursor is not None:
            values = self._annotation_cursors.decode_keyset(
                cursor=parsed.cursor,
                fingerprint=fingerprint,
                arity=7,
            )
            try:
                created_at = datetime.fromisoformat(values[5])
                if created_at.tzinfo is None:
                    raise ValueError("annotation cursor timestamp requires a timezone")
                anchor_y = float(values[1]) if values[1] else None
                anchor_x = float(values[2]) if values[2] else None
                if any(
                    value is not None and not math.isfinite(value)
                    for value in (anchor_y, anchor_x)
                ):
                    raise ValueError("annotation cursor coordinates must be finite")
                after = AnnotationThreadSummaryKeyset(
                    page_number=int(values[0]) if values[0] else None,
                    anchor_y=anchor_y,
                    anchor_x=anchor_x,
                    start_offset=int(values[3]) if values[3] else None,
                    end_offset=int(values[4]) if values[4] else None,
                    created_at=created_at,
                    item_id=UUID(values[6]),
                )
            except (TypeError, ValueError) as exc:
                raise AppError(
                    code="annotation_thread_cursor_invalid",
                    message="The annotation thread cursor is invalid or expired",
                    kind=FailureKind.INVALID_ARGUMENT,
                ) from exc
        result = capabilities.research_items.list_annotation_thread_summaries_page(
            actor=context.actor,
            document_id=parsed.document_id,
            project_id=parsed.project_id,
            audience=parsed.audience,
            mode=parsed.mode,
            status=parsed.status,
            after=after,
            limit=min(parsed.limit, ANNOTATION_SUMMARY_MAX_PAGE_ITEMS),
        )
        page = result.items
        keyset = result.next_keyset
        next_cursor = (
            self._annotation_cursors.encode_keyset(
                fingerprint=fingerprint,
                values=(
                    str(keyset.page_number) if keyset.page_number is not None else "",
                    str(keyset.anchor_y) if keyset.anchor_y is not None else "",
                    str(keyset.anchor_x) if keyset.anchor_x is not None else "",
                    str(keyset.start_offset) if keyset.start_offset is not None else "",
                    str(keyset.end_offset) if keyset.end_offset is not None else "",
                    keyset.created_at.isoformat(),
                    str(keyset.item_id),
                ),
            )
            if keyset is not None
            else None
        )
        return ToolOutcome(
            payload=_json(
                wc.ThreadListOutput(
                    items=[
                        wc.AnnotationThreadSummaryToolResponse(
                            **item.model_dump(),
                            reader_url=self._thread_summary_reader_url(
                                item,
                                project_id=parsed.project_id,
                            ),
                        )
                        for item in page
                    ],
                    next_cursor=next_cursor,
                )
            ),
            resource_links=tuple(_thread_link(item.id) for item in page),
        )

    def get_annotation_thread(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.AnnotationThreadInput.model_validate(arguments)
        access = capabilities.research_items.lock_legacy_read(
            actor=context.actor,
            item_id=parsed.thread_id,
        )
        if access.kind is not ResearchItemKind.ANNOTATION_THREAD:
            raise AppError(
                code="annotation_thread_not_found",
                message="Annotation thread not found",
                kind=FailureKind.NOT_FOUND,
            )
        require_legacy_payload_budget(
            payload_json_utf8_upper_bound=(access.legacy_payload_json_utf8_upper_bound),
            tool="get_annotation_thread",
            replacement_tool="get_annotation_thread_page",
        )
        result = capabilities.research_items.get_annotation_thread(
            actor=context.actor, thread_id=parsed.thread_id
        )
        current = capabilities.research_items.authorize_page(
            actor=context.actor,
            item_id=parsed.thread_id,
        )
        if current.revision != access.revision:
            raise AppError(
                code="research_output_snapshot_changed",
                message="The annotation thread changed while it was prepared",
                kind=FailureKind.CONFLICT,
            )
        return ToolOutcome(
            payload=_json(
                wc.ResearchItemToolResponse(
                    **result.model_dump(),
                    reader_url=self._research_reader_url(result),
                )
            ),
            resource_links=(_thread_link(parsed.thread_id),),
        )

    def get_annotation_thread_page(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.AnnotationThreadPageInput.model_validate(arguments)
        page, _kind = self._research_output_page(
            capabilities=capabilities,
            context=context,
            item_id=parsed.thread_id,
            cursor=parsed.cursor,
            max_utf8_bytes=parsed.max_utf8_bytes,
            required_kind=ResearchItemKind.ANNOTATION_THREAD,
        )
        reader_url = self._research_reader_urls.get(parsed.thread_id)
        return ToolOutcome(
            payload=_json(
                wc.PaperJsonDocumentPageOutput(
                    **page.model_dump(),
                    reader_url=reader_url,
                )
            ),
            resource_links=(_thread_link(parsed.thread_id),),
        )

    def annotate_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        """Create a visually paintable annotation from quote text alone."""

        parsed = wc.AnnotatePaperInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
            project_id=getattr(parsed.audience, "project_id", None),
        )
        snapshot = self._authorized_paper_content_snapshot(
            capabilities=capabilities,
            context=context,
            document_id=parsed.document_id,
        )
        if (
            parsed.content_sha256 is not None
            and parsed.content_sha256 != snapshot.content_sha256
        ):
            raise AppError(
                code="annotation_content_changed",
                message=(
                    "Paper text changed since content_sha256 was read; fetch the "
                    "latest paper content and retry"
                ),
                kind=FailureKind.CONFLICT,
                details={"expected_content_sha256": parsed.content_sha256},
            )
        try:
            target = resolve_annotation_quote(
                content=snapshot.pager.raw_content,
                quote_text=parsed.quote_text,
            )
        except AppError as error:
            logger.info(
                "research.annotation_target_resolution_failed",
                extra={
                    "annotation_error_code": error.code,
                    "document_id": str(parsed.document_id),
                    "quote_chars": len(parsed.quote_text),
                },
            )
            raise
        logger.info(
            "research.annotation_target_resolved",
            extra={
                "document_id": str(parsed.document_id),
                "quote_chars": len(parsed.quote_text),
                "start_offset": target.start_offset,
                "end_offset": target.end_offset,
            },
        )
        position = ParsedTextPosition(
            start_offset=target.start_offset,
            end_offset=target.end_offset,
        )
        result = capabilities.research_items.create_annotation_thread(
            actor=context.actor,
            operation=context.operation,
            content_role=RoleType.ASSISTANT,
            document_id=parsed.document_id,
            request=CreateAnnotationThreadRequest(
                quote_text=parsed.quote_text,
                position=position,
                color=parsed.color,
                audience=parsed.audience,
                initial_comment=parsed.comment,
            ),
        )
        projection = project_annotation_thread(result)
        resource_uri = f"scholens://annotation-threads/{result.id}"
        reader_url = self._research_reader_url(
            projection.thread,
            project_id=getattr(parsed.audience, "project_id", None),
        )
        payload = wc.ThreadActionOutput(
            thread=wc.ResearchItemToolResponse(
                **projection.thread.model_dump(),
                reader_url=reader_url,
            ),
            resource_uri=resource_uri,
            reader_url=reader_url,
            content_truncated=projection.content_truncated,
            guidance=(
                "Use get_annotation_thread_page to read the complete stored quote, "
                "position, and comments."
                if projection.content_truncated
                else None
            ),
            anchor=position,
            visual_treatment="underline" if parsed.comment else "highlight",
            next_action=(
                "Open the returned resource_uri; this anchor is immediately paintable "
                "in the Reader."
            ),
        )
        return ToolOutcome(
            payload=_json(payload),
            action={
                "kind": "annotation_thread_created",
                "thread_id": str(result.id),
                "resource_uri": resource_uri,
                "content_truncated": projection.content_truncated,
                "anchor_resolved": True,
            },
            resource_links=(_thread_link(result.id), _paper_link(parsed.document_id)),
        )

    def create_annotation_thread(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.CreateAnnotationThreadInput.model_validate(arguments)
        self._require_paper(
            capabilities,
            context,
            parsed.document_id,
            project_id=getattr(parsed.audience, "project_id", None),
        )
        result = capabilities.research_items.create_annotation_thread(
            actor=context.actor,
            operation=context.operation,
            content_role=RoleType.ASSISTANT,
            document_id=parsed.document_id,
            request=CreateAnnotationThreadRequest(
                quote_text=parsed.quote_text,
                position=parsed.position,
                color=parsed.color,
                audience=parsed.audience,
                initial_comment=parsed.initial_comment,
            ),
        )
        projection = project_annotation_thread(result)
        resource_uri = f"scholens://annotation-threads/{result.id}"
        reader_url = self._research_reader_url(
            projection.thread,
            project_id=getattr(parsed.audience, "project_id", None),
        )
        payload = wc.ThreadActionOutput(
            thread=wc.ResearchItemToolResponse(
                **projection.thread.model_dump(),
                reader_url=reader_url,
            ),
            resource_uri=resource_uri,
            reader_url=reader_url,
            content_truncated=projection.content_truncated,
            guidance=(
                "Use get_annotation_thread_page to read the complete stored quote, "
                "position, and comments."
                if projection.content_truncated
                else None
            ),
        )
        return ToolOutcome(
            payload=_json(payload),
            action={
                "kind": "annotation_thread_created",
                "thread_id": str(result.id),
                "resource_uri": resource_uri,
                "content_truncated": projection.content_truncated,
            },
            resource_links=(_thread_link(result.id), _paper_link(parsed.document_id)),
        )

    def update_annotation_thread(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.UpdateAnnotationThreadInput.model_validate(arguments)
        result = capabilities.research_items.update_annotation_thread_bounded(
            actor=context.actor,
            operation=context.operation,
            thread_id=parsed.thread_id,
            request=UpdateAnnotationThreadRequest(
                color=parsed.color, status=parsed.status
            ),
        )
        projection = project_annotation_thread(result)
        resource_uri = f"scholens://annotation-threads/{result.id}"
        reader_url = self._research_reader_url(projection.thread)
        payload = wc.ThreadActionOutput(
            thread=wc.ResearchItemToolResponse(
                **projection.thread.model_dump(),
                reader_url=reader_url,
            ),
            resource_uri=resource_uri,
            reader_url=reader_url,
            content_truncated=projection.content_truncated,
            guidance=(
                "Use get_annotation_thread_page to read the complete stored quote, "
                "position, and comments."
                if projection.content_truncated
                else None
            ),
        )
        return ToolOutcome(
            payload=_json(payload),
            action={
                "kind": "annotation_thread_updated",
                "thread_id": str(result.id),
                "resource_uri": resource_uri,
                "content_truncated": projection.content_truncated,
            },
            resource_links=(_thread_link(result.id),),
        )

    def delete_annotation_thread(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DeleteAnnotationThreadInput.model_validate(arguments)
        plan = capabilities.research_items.plan_annotation_thread_delete(
            actor=context.actor, thread_id=parsed.thread_id
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="delete_annotation_thread",
            state=plan.state,
            impact=ActionImpact(
                title="Delete annotation thread",
                summary="Delete this annotation thread and its discussion.",
                consequences=[
                    f"Delete {plan.state.comment_count} comments. Threads with "
                    "replies from other contributors cannot be deleted."
                ],
                affected_resources=[f"annotation_thread:{parsed.thread_id}"],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.research_items.delete_annotation_thread(
            actor=context.actor, operation=context.operation, thread_id=parsed.thread_id
        )
        return self._completed(
            action="annotation_thread_deleted",
            affected_resources=[f"annotation_thread:{parsed.thread_id}"],
        )

    def create_annotation_comment(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.CreateAnnotationCommentInput.model_validate(arguments)
        result = capabilities.research_items.create_comment(
            actor=context.actor,
            operation=context.operation,
            content_role=RoleType.ASSISTANT,
            thread_id=parsed.thread_id,
            request=CreateAnnotationCommentRequest(content=parsed.content),
        )
        projection = project_annotation_comment(result)
        resource_uri = f"scholens://annotation-threads/{parsed.thread_id}"
        payload = wc.CommentActionOutput(
            comment=projection.comment,
            resource_uri=resource_uri,
            reader_url=self._comment_reader_url(
                capabilities,
                context,
                parsed.thread_id,
            ),
            content_truncated=projection.content_truncated,
            guidance=(
                "Use get_annotation_thread_page to read the complete stored comment."
                if projection.content_truncated
                else None
            ),
        )
        return ToolOutcome(
            payload=_json(payload),
            action={
                "kind": "annotation_comment_created",
                "comment_id": str(result.id),
                "thread_id": str(result.thread_id),
                "resource_uri": resource_uri,
                "content_truncated": projection.content_truncated,
            },
            resource_links=(_thread_link(parsed.thread_id),),
        )

    def update_annotation_comment(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.UpdateAnnotationCommentInput.model_validate(arguments)
        result = capabilities.research_items.update_comment(
            actor=context.actor,
            operation=context.operation,
            comment_id=parsed.comment_id,
            request=UpdateAnnotationCommentRequest(content=parsed.content),
        )
        projection = project_annotation_comment(result)
        resource_uri = f"scholens://annotation-threads/{result.thread_id}"
        payload = wc.CommentActionOutput(
            comment=projection.comment,
            resource_uri=resource_uri,
            reader_url=self._comment_reader_url(
                capabilities,
                context,
                result.thread_id,
            ),
            content_truncated=projection.content_truncated,
            guidance=(
                "Use get_annotation_thread_page to read the complete stored comment."
                if projection.content_truncated
                else None
            ),
        )
        return ToolOutcome(
            payload=_json(payload),
            action={
                "kind": "annotation_comment_updated",
                "comment_id": str(result.id),
                "thread_id": str(result.thread_id),
                "resource_uri": resource_uri,
                "content_truncated": projection.content_truncated,
            },
            resource_links=(_thread_link(result.thread_id),),
        )

    def delete_annotation_comment(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DeleteAnnotationCommentInput.model_validate(arguments)
        comment = capabilities.research_items.get_comment(
            actor=context.actor, comment_id=parsed.comment_id
        )
        if not comment.can_delete:
            raise AppError(
                code="annotation_comment_not_found",
                message="Annotation comment not found",
                kind=FailureKind.NOT_FOUND,
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="delete_annotation_comment",
            state=comment,
            impact=ActionImpact(
                title="Delete annotation comment",
                summary="Permanently delete this comment from its annotation thread.",
                consequences=[f"Comment preview: {comment.content[:240]}"],
                affected_resources=[
                    f"annotation_comment:{parsed.comment_id}",
                    f"annotation_thread:{comment.thread_id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.research_items.delete_comment(
            actor=context.actor,
            operation=context.operation,
            comment_id=parsed.comment_id,
        )
        return self._completed(
            action="annotation_comment_deleted",
            affected_resources=[
                f"annotation_comment:{parsed.comment_id}",
                f"annotation_thread:{comment.thread_id}",
            ],
            links=(_thread_link(comment.thread_id),),
        )

    def list_research_outputs(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListResearchOutputsInput.model_validate(arguments)
        kinds = tuple(sorted(set(parsed.kinds), key=lambda kind: kind.value))
        output: wc.ResearchOutputList
        if parsed.scope.kind == "library":
            library_page = capabilities.paper_library.list_outputs(
                actor=context.actor,
                query=parsed.query,
                kinds=kinds,
                sort=parsed.sort,
                cursor=parsed.cursor,
                limit=parsed.limit,
                maximum_payload_json_bytes=_LEGACY_TOOL_DURABLE_JSON_UTF8_BYTES,
            )
            output = wc.ResearchOutputList(
                items=[
                    self._research_output_tool_entry(entry)
                    for entry in library_page.items
                ],
                next_cursor=library_page.next_cursor,
                previous_cursor=library_page.previous_cursor,
                total_count=library_page.total_count,
            )
        elif parsed.scope.kind == "project":
            project_page = capabilities.projects.outputs(
                actor=context.actor,
                project_id=parsed.scope.project_id,
                query=parsed.query,
                kinds=kinds,
                sort=parsed.sort,
                cursor=parsed.cursor,
                limit=parsed.limit,
                maximum_payload_json_bytes=_LEGACY_TOOL_DURABLE_JSON_UTF8_BYTES,
            )
            output = wc.ResearchOutputList(
                items=[
                    self._research_output_tool_entry(
                        entry,
                        project_id=parsed.scope.project_id,
                    )
                    for entry in project_page.items
                ],
                next_cursor=project_page.next_cursor,
                previous_cursor=project_page.previous_cursor,
                total_count=project_page.total_count,
            )
        else:
            paper_page = capabilities.research_items.list_document_legacy(
                actor=context.actor,
                document_id=parsed.scope.document_id,
                project_id=parsed.scope.project_id,
                query=parsed.query,
                kinds=kinds,
                limit=parsed.limit,
                maximum_payload_json_bytes=_LEGACY_TOOL_DURABLE_JSON_UTF8_BYTES,
            )
            output_items = [
                self._research_output_tool_entry(
                    entry,
                    project_id=parsed.scope.project_id,
                )
                for entry in paper_page.items
            ]
            output = wc.ResearchOutputList(
                items=output_items,
                total_count=paper_page.total_count,
            )
        return ToolOutcome(
            payload=_json(output),
            resource_links=tuple(
                _research_item_link(
                    entry.item if isinstance(entry, LibraryOutputResponse) else entry
                )
                for entry in output.items
            ),
        )

    def list_research_output_summaries(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListResearchOutputSummariesInput.model_validate(arguments)
        result = self._list_research_output_summaries(
            capabilities=capabilities,
            context=context,
            parsed=parsed,
            limit=parsed.limit,
        )
        project_id = parsed.scope.project_id if parsed.scope.kind == "project" else None
        projected = wc.ResearchOutputSummaryListToolResponse(
            items=[
                self._research_summary_tool_response(item, project_id=project_id)
                for item in result.items
            ],
            next_cursor=result.next_cursor,
            previous_cursor=result.previous_cursor,
            total_count=result.total_count,
        )
        links = tuple(
            (
                _thread_link(item.item_id)
                if item.kind is ResearchItemKind.ANNOTATION_THREAD
                else _output_link(item.item_id)
            )
            for item in projected.items
        )
        return ToolOutcome(payload=_json(projected), resource_links=links)

    @staticmethod
    def _list_research_output_summaries(
        *,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        parsed: wc.ListResearchOutputsInput,
        limit: int,
    ) -> ResearchOutputSummaryListResponse:
        kinds = tuple(sorted(set(parsed.kinds), key=lambda kind: kind.value))
        if parsed.scope.kind == "library":
            scope = ResearchOutputCatalogScope.library()
        elif parsed.scope.kind == "project":
            scope = ResearchOutputCatalogScope.project(parsed.scope.project_id)
        else:
            scope = ResearchOutputCatalogScope.paper(
                parsed.scope.document_id,
                project_id=parsed.scope.project_id,
            )
        return capabilities.research_output_catalog.list(
            actor=context.actor,
            scope=scope,
            query=parsed.query,
            kinds=kinds,
            sort=ResearchOutputCatalogSort(parsed.sort.value),
            cursor=parsed.cursor,
            limit=limit,
        )

    def get_research_output(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ResearchOutputInput.model_validate(arguments)
        access = capabilities.research_items.lock_legacy_read(
            actor=context.actor,
            item_id=parsed.item_id,
        )
        if access.kind not in _RESEARCH_OUTPUT_KINDS:
            raise AppError(
                code="research_output_not_found",
                message="The requested item is not a supported research output",
                kind=FailureKind.NOT_FOUND,
            )
        require_legacy_payload_budget(
            payload_json_utf8_upper_bound=(access.legacy_payload_json_utf8_upper_bound),
            tool="get_research_output",
            replacement_tool="get_research_output_page",
        )
        result: ResearchItemResponse = capabilities.research_items.get_item(
            actor=context.actor, item_id=parsed.item_id
        )
        if result.kind not in _RESEARCH_OUTPUT_KINDS:
            raise AppError(
                code="research_output_not_found",
                message="The requested item is not a supported research output",
                kind=FailureKind.NOT_FOUND,
            )
        current = capabilities.research_items.authorize_page(
            actor=context.actor,
            item_id=parsed.item_id,
        )
        if current.revision != access.revision:
            raise AppError(
                code="research_output_snapshot_changed",
                message="The research output changed while it was prepared",
                kind=FailureKind.CONFLICT,
            )
        return ToolOutcome(
            payload=_json(self._research_item_tool_response(result)),
            resource_links=(_research_item_link(result),),
        )

    def get_research_output_page(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ResearchOutputPageInput.model_validate(arguments)
        page, kind = self._research_output_page(
            capabilities=capabilities,
            context=context,
            item_id=parsed.item_id,
            cursor=parsed.cursor,
            max_utf8_bytes=parsed.max_utf8_bytes,
        )
        reader_url = self._research_reader_urls.get(parsed.item_id)
        return ToolOutcome(
            payload=_json(
                wc.PaperJsonDocumentPageOutput(
                    **page.model_dump(),
                    reader_url=reader_url,
                )
            ),
            resource_links=(
                _thread_link(parsed.item_id)
                if kind is ResearchItemKind.ANNOTATION_THREAD
                else _output_link(parsed.item_id),
            ),
        )

    def _research_output_page(
        self,
        *,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        item_id: UUID,
        cursor: str | None,
        max_utf8_bytes: int,
        required_kind: ResearchItemKind | None = None,
    ) -> tuple[wc.JsonDocumentPageOutput, ResearchItemKind]:
        for _attempt in range(2):
            access: ResearchItemPageAccess = capabilities.research_items.authorize_page(
                actor=context.actor,
                item_id=item_id,
            )
            if access.kind not in _RESEARCH_OUTPUT_KINDS or (
                required_kind is not None and access.kind is not required_kind
            ):
                raise AppError(
                    code=(
                        "annotation_thread_not_found"
                        if required_kind is ResearchItemKind.ANNOTATION_THREAD
                        else "research_output_not_found"
                    ),
                    message="The requested item is not a supported research output",
                    kind=FailureKind.NOT_FOUND,
                )
            if (
                access.durable_json_utf8_upper_bound
                > self._json_document_page_cache.max_entry_utf8_bytes
            ):
                raise AppError(
                    code="json_document_paging_limit_exceeded",
                    message=(
                        "The canonical JSON document exceeds the supported lossless "
                        "paging limit"
                    ),
                    kind=FailureKind.PAYLOAD_TOO_LARGE,
                    details={
                        "durable_json_utf8_upper_bound": (
                            access.durable_json_utf8_upper_bound
                        ),
                        "maximum_utf8_bytes": (
                            self._json_document_page_cache.max_entry_utf8_bytes
                        ),
                    },
                )
            resource_uri = (
                f"scholens://annotation-threads/{item_id}"
                if access.kind is ResearchItemKind.ANNOTATION_THREAD
                else f"scholens://research-outputs/{item_id}"
            )

            def durable_value() -> object:
                result: ResearchItemResponse = capabilities.research_items.get_item(
                    actor=context.actor,
                    item_id=item_id,
                )
                latest = capabilities.research_items.authorize_page(
                    actor=context.actor,
                    item_id=item_id,
                )
                if result.kind is not access.kind or latest.revision != access.revision:
                    raise _ResearchRevisionAdvanced
                export = result.model_dump(mode="json")
                audio = export.get("audio_overview")
                if isinstance(audio, dict):
                    audio.pop("audio_url", None)
                    audio["audio_access"] = "Use the page-level access_url."
                self._research_reader_urls[item_id] = self._research_reader_url(result)
                return export

            try:
                pager = self._cached_json_document_pager(
                    key=(
                        context.actor.id,
                        resource_uri,
                        str(item_id),
                        access.revision,
                    ),
                    value_factory=durable_value,
                )
            except _ResearchRevisionAdvanced:
                continue
            return (
                self._json_document_page(
                    actor_id=context.actor.id,
                    resource_uri=resource_uri,
                    pager=pager,
                    cursor=cursor,
                    max_utf8_bytes=max_utf8_bytes,
                    cursors=self._research_document_cursors,
                    cursor_error_code="research_output_cursor_invalid",
                    access_url=access.access_url,
                    revision=access.revision,
                ),
                access.kind,
            )
        raise AppError(
            code="research_output_cursor_invalid",
            message="The research output changed while the page was prepared",
            kind=FailureKind.CONFLICT,
        )


__all__ = ["WorkspaceToolHandlers"]
