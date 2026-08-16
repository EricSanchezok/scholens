"""Business-tool handlers composed exclusively from Application capabilities."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import cast
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.action_confirmations.application import confirmation_digest
from app.modules.action_confirmations.contracts import ActionImpact
from app.modules.papers.application.contracts.citation import CitationData
from app.modules.papers.application.contracts.documents import LibraryPaperUpdateRequest
from app.modules.papers.application.contracts.documents import LibraryOutputResponse
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
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
from app.modules.papers.domain.citations import (
    missing_required_fields,
    normalize_style,
)
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectCollaboratorUpdateRequest,
    ProjectCreateRequest,
    ProjectInvitationCreateRequest,
    ProjectInvitationResponse,
    ProjectResponse,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.modules.research.application.contracts import (
    CreateAnnotationCommentRequest,
    CreateAnnotationThreadRequest,
    ResearchItemResponse,
    UpdateAnnotationCommentRequest,
    UpdateAnnotationThreadRequest,
)
from app.modules.research.application.search import ResearchSearchRequest
from app.shared.application import ApplicationExecutor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind, RoleType
from app.tooling.contracts import (
    DocumentSourceCandidate,
    ToolExecutionContext,
    ToolOutcome,
    ToolResourceLink,
)
from app.tooling import workspace_contracts as wc
from pydantic import BaseModel, TypeAdapter

_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_OUTPUT_KINDS = {
    ResearchItemKind.CITATION,
    ResearchItemKind.AUDIO_OVERVIEW,
    ResearchItemKind.DATA_TABLE,
}


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


def _resource_link(uri: str, name: str, description: str) -> ToolResourceLink:
    return ToolResourceLink(uri=uri, name=name, description=description)


def _paper_link(document_id: UUID, title: str | None = None) -> ToolResourceLink:
    return _resource_link(
        f"scholens://papers/{document_id}",
        title or f"Paper {document_id}",
        "Canonical Scholens paper metadata. Use get_paper_content for bounded text.",
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
        "Stored citation, audio overview, or data-table output.",
    )


def _document_source(
    *,
    document_id: UUID,
    excerpt: str,
    title: str | None = None,
    authors: list[str] | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> DocumentSourceCandidate:
    locator: dict[str, JsonValue] = {}
    if start_line is not None:
        locator["start_line"] = start_line
    if end_line is not None:
        locator["end_line"] = end_line
    return DocumentSourceCandidate(
        document_id=document_id,
        excerpt=excerpt,
        title=title,
        authors=tuple(authors or ()),
        locator=locator or None,
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
    ) -> None:
        self._executor = executor
        self._ingestion = ingestion
        self._citations = citations
        self._web_base_url = web_base_url.rstrip("/")
        self._knowledge_cursors = SignedCursorCodec(
            cursor_secret,
            revision="scholens-knowledge:1",
            error_code="knowledge_search_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )
        self._annotation_cursors = SignedCursorCodec(
            cursor_secret,
            revision="annotation-thread-tools:1",
            error_code="annotation_thread_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        )

    @staticmethod
    def _require_paper(
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        document_id: UUID,
    ) -> None:
        capabilities.paper_collection_access(
            actor=context.actor,
            collection=context.paper_collection,
            document_id=document_id,
            anchor_document_id=context.anchor_document_id,
        )

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
        payload = wc.CompletedAction(
            action=action,
            changed=changed,
            affected_resources=affected_resources,
            result=_json_object(result) if result is not None else None,
            guidance=guidance,
        )
        return ToolOutcome(
            payload=_json(payload),
            action=_json_object(payload),
            resource_links=links,
        )

    def search_knowledge(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.SearchKnowledgeInput.model_validate(arguments)
        fingerprint = json.dumps(
            parsed.model_dump(mode="json", exclude={"cursor"}),
            separators=(",", ":"),
            sort_keys=True,
        )
        offset = (
            self._knowledge_cursors.decode(
                cursor=parsed.cursor,
                fingerprint=fingerprint,
            )
            if parsed.cursor
            else 0
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
                document_ids=[parsed.scope.document_id]
            )
        else:  # pragma: no cover - the discriminated union is exhaustive
            raise AssertionError("unsupported knowledge scope")
        requested_kinds = set(parsed.kinds)

        def include(kind: str) -> bool:
            return not requested_kinds or kind in requested_kinds

        candidates: list[wc.KnowledgeSearchResult] = []
        paper_response = capabilities.paper_search(
            actor=context.actor,
            request=PaperSearchRequest(
                query=parsed.query,
                collection=paper_collection,
                filters=parsed.filters,
                sort=parsed.sort,
                limit=100,
            ),
        )
        needle = parsed.query.casefold()
        for paper in paper_response.items:
            score = 1.0 + sum(
                value.casefold().count(needle)
                for value in (paper.title or "", paper.abstract or "")
            )
            if include("paper"):
                candidates.append(
                    wc.KnowledgeSearchResult(
                        kind="paper",
                        resource_uri=f"scholens://papers/{paper.document_id}",
                        title=paper.title,
                        excerpt=(paper.abstract or paper.title or "Stored paper")[
                            :1_200
                        ],
                        score=score,
                        document_id=paper.document_id,
                        project_id=(
                            parsed.scope.project_id
                            if parsed.scope.kind == "project"
                            else None
                        ),
                        entity_id=paper.document_id,
                        updated_at=paper.last_accessed_at,
                    )
                )
            if include("paper_passage"):
                for snippet in paper.snippets:
                    candidates.append(
                        wc.KnowledgeSearchResult(
                            kind="paper_passage",
                            resource_uri=f"scholens://papers/{paper.document_id}",
                            title=paper.title,
                            excerpt=snippet.text[:1_200],
                            score=score + 0.5,
                            document_id=paper.document_id,
                            project_id=(
                                parsed.scope.project_id
                                if parsed.scope.kind == "project"
                                else None
                            ),
                            entity_id=paper.document_id,
                            locator={
                                "start_line": snippet.start_line,
                                "end_line": snippet.end_line,
                            },
                            updated_at=paper.last_accessed_at,
                        )
                    )
        research_response = capabilities.research_search(
            actor=context.actor,
            request=ResearchSearchRequest(query=parsed.query, limit=100),
        )
        for thread in research_response.items:
            if (
                parsed.scope.kind == "project"
                and thread.project_id != parsed.scope.project_id
            ):
                continue
            if (
                parsed.scope.kind == "paper"
                and thread.document_id != parsed.scope.document_id
            ):
                continue
            if parsed.scope.kind == "paper":
                allowed_project_ids = {None, parsed.scope.project_id}
                if thread.project_id not in allowed_project_ids:
                    continue
            if parsed.scope.kind == "library":
                if thread.project_id is not None or not (
                    capabilities.paper_collection_access.contains(
                        actor=context.actor,
                        collection=PersonalLibraryPaperCollection(),
                        document_id=thread.document_id,
                    )
                ):
                    continue
            if include("annotation_thread"):
                candidates.append(
                    wc.KnowledgeSearchResult(
                        kind="annotation_thread",
                        resource_uri=f"scholens://annotation-threads/{thread.id}",
                        title=thread.document_title,
                        excerpt=thread.quote_text[:1_200],
                        score=1.5 + thread.quote_text.casefold().count(needle),
                        document_id=thread.document_id,
                        project_id=thread.project_id,
                        entity_id=thread.id,
                        locator=(
                            _json_object(thread.position)
                            if thread.position is not None
                            else None
                        ),
                        updated_at=thread.created_at,
                    )
                )
            if include("annotation_comment"):
                for comment in thread.matching_comments:
                    candidates.append(
                        wc.KnowledgeSearchResult(
                            kind="annotation_comment",
                            resource_uri=f"scholens://annotation-threads/{thread.id}",
                            title=thread.document_title,
                            excerpt=comment.content[:1_200],
                            score=1.5 + comment.content.casefold().count(needle),
                            document_id=thread.document_id,
                            project_id=thread.project_id,
                            entity_id=comment.id,
                            locator={"thread_id": str(thread.id)},
                            updated_at=comment.created_at,
                        )
                    )
        if include("research_output"):
            output_entries: list[LibraryOutputResponse | ResearchItemResponse]
            if parsed.scope.kind == "project":
                project_output_page = capabilities.projects.outputs(
                    actor=context.actor,
                    project_id=parsed.scope.project_id,
                    query=parsed.query,
                    kinds=tuple(_OUTPUT_KINDS),
                    limit=100,
                )
                output_entries = list(project_output_page.items)
            elif parsed.scope.kind == "paper":
                output_entries = [
                    item
                    for item in capabilities.research_items.list_document(
                        actor=context.actor,
                        document_id=parsed.scope.document_id,
                        project_id=parsed.scope.project_id,
                    ).items
                    if item.kind in _OUTPUT_KINDS
                    and needle
                    in json.dumps(
                        item.model_dump(mode="json"), ensure_ascii=False
                    ).casefold()
                ]
            else:
                library_output_page = capabilities.paper_library.list_outputs(
                    actor=context.actor,
                    query=parsed.query,
                    kinds=tuple(_OUTPUT_KINDS),
                    limit=100,
                )
                library_entries = list(library_output_page.items)
                if parsed.scope.kind == "library":
                    library_entries = [
                        entry
                        for entry in library_entries
                        if entry.source.audience_type is ResearchAudienceType.PERSONAL
                        or (
                            entry.source.audience_type is ResearchAudienceType.DOCUMENT
                            and entry.source.audience_id is not None
                            and capabilities.paper_collection_access.contains(
                                actor=context.actor,
                                collection=PersonalLibraryPaperCollection(),
                                document_id=entry.source.audience_id,
                            )
                        )
                    ]
                output_entries = list(library_entries)
            for entry in output_entries:
                if isinstance(entry, LibraryOutputResponse):
                    item = entry.item
                    title = entry.title
                else:
                    item = entry
                    title = None
                document_id = item.target_document_id
                project_id = getattr(item.audience, "project_id", None)
                serialized = json.dumps(
                    item.model_dump(mode="json"), ensure_ascii=False
                )
                candidates.append(
                    wc.KnowledgeSearchResult(
                        kind="research_output",
                        resource_uri=f"scholens://research-outputs/{item.id}",
                        title=title,
                        excerpt=serialized[:1_200],
                        score=1.0 + serialized.casefold().count(needle),
                        document_id=document_id,
                        project_id=project_id,
                        entity_id=item.id,
                        updated_at=item.updated_at,
                    )
                )
        if parsed.sort.value == "recent":
            candidates.sort(
                key=lambda item: (item.updated_at, str(item.entity_id)), reverse=True
            )
        else:
            candidates.sort(
                key=lambda item: (item.score, item.updated_at, str(item.entity_id)),
                reverse=True,
            )
        page = candidates[offset : offset + parsed.limit]
        consumed = offset + len(page)
        result = wc.KnowledgeSearchOutput(
            items=page,
            next_cursor=(
                self._knowledge_cursors.encode(
                    fingerprint=fingerprint,
                    offset=consumed,
                )
                if consumed < len(candidates)
                else None
            ),
            searched_scope=parsed.scope,
        )
        sources = tuple(
            _document_source(
                document_id=item.document_id,
                excerpt=item.excerpt,
                title=item.title,
                start_line=cast(int | None, (item.locator or {}).get("start_line")),
                end_line=cast(int | None, (item.locator or {}).get("end_line")),
            )
            for item in result.items
            if item.document_id is not None and item.kind in {"paper", "paper_passage"}
        )
        return ToolOutcome(payload=_json(result), sources=sources)

    def get_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DocumentInput.model_validate(arguments)
        self._require_paper(capabilities, context, parsed.document_id)
        result = capabilities.paper_details(
            actor=context.actor,
            document_id=parsed.document_id,
        )
        return ToolOutcome(
            payload=_json(result),
            resource_links=(_paper_link(parsed.document_id, result.title),),
        )

    def get_paper_content(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.PaperContentInput.model_validate(arguments)
        self._require_paper(capabilities, context, parsed.document_id)
        paper = capabilities.paper_content.read(
            actor=context.actor,
            document_id=parsed.document_id,
        )
        source_lines = paper.raw_content.splitlines() if paper.raw_content else []
        if source_lines and parsed.start_line > len(source_lines):
            raise AppError(
                code="paper_content_start_invalid",
                message="start_line is after the end of the extracted paper text",
                kind=FailureKind.INVALID_ARGUMENT,
                details={"total_lines": len(source_lines)},
            )
        selected = source_lines[
            parsed.start_line - 1 : parsed.start_line - 1 + parsed.max_lines
        ]
        numbered = [
            f"{parsed.start_line + offset}: {line}"
            for offset, line in enumerate(selected)
        ]
        end_line = parsed.start_line + len(selected) - 1 if selected else None
        next_start = (
            end_line + 1
            if end_line is not None and end_line < len(source_lines)
            else None
        )
        content_sha = (
            hashlib.sha256(paper.raw_content.encode()).hexdigest()
            if paper.raw_content is not None
            else None
        )
        result = wc.PaperContentOutput(
            document_id=parsed.document_id,
            title=paper.title,
            start_line=parsed.start_line,
            end_line=end_line,
            total_lines=len(source_lines),
            lines=numbered,
            next_start_line=next_start,
            content_sha256=content_sha,
        )
        return ToolOutcome(
            payload=_json(result),
            sources=tuple(
                _document_source(
                    document_id=parsed.document_id,
                    excerpt=line.partition(": ")[2],
                    title=paper.title,
                    start_line=parsed.start_line + offset,
                    end_line=parsed.start_line + offset,
                )
                for offset, line in enumerate(numbered)
            ),
            resource_links=(_paper_link(parsed.document_id, paper.title),),
        )

    def search_paper_content(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.SearchPaperContentInput.model_validate(arguments)
        self._require_paper(capabilities, context, parsed.document_id)
        matches = capabilities.paper_content.search_document(
            actor=context.actor,
            document_id=parsed.document_id,
            query=parsed.query,
        )
        result = wc.PaperContentSearchOutput(
            document_id=parsed.document_id,
            matches=matches,
            match_count=len(matches),
            guidance=(
                "Use get_paper_content with the returned line numbers to read enough "
                "surrounding context before drawing a conclusion or creating an annotation."
            ),
        )
        sources: list[DocumentSourceCandidate] = []
        for match in matches:
            prefix, separator, excerpt = match.partition(": ")
            line = int(prefix) if separator and prefix.isdigit() else None
            sources.append(
                _document_source(
                    document_id=parsed.document_id,
                    excerpt=excerpt if separator else match,
                    start_line=line,
                    end_line=line,
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
        self._require_paper(capabilities, context, parsed.document_id)
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
        result = wc.PaperCitationReadOutput(
            document_id=parsed.document_id,
            preferred_style=style,
            data=CitationData(
                document_id=str(parsed.document_id),
                title=fields.title,
                authors=fields.authors,
                publish_date=fields.publish_date,
                journal=fields.journal,
                publisher=fields.publisher,
                doi=fields.doi,
            ),
            missing_fields=missing,
            complete=not missing,
            guidance=(
                "Use resolve_paper_citation only if required fields are missing; that "
                "workflow may contact metadata providers and persist recovered fields."
                if missing
                else "Use the structured fields to render the requested citation style."
            ),
        )
        return ToolOutcome(
            payload=_json(result),
            resource_links=(_paper_link(parsed.document_id, fields.title),),
        )

    async def resolve_paper_citation(
        self,
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
    ) -> ToolOutcome:
        del invocation_key
        parsed = wc.ResolvePaperCitationInput.model_validate(arguments)
        citation = await asyncio.to_thread(
            self._citations.run,
            actor=context.actor,
            operation=context.operation,
            document_id=parsed.document_id,
            style=parsed.style,
            project_id=parsed.project_id,
            paper_collection=context.paper_collection,
            anchor_document_id=context.anchor_document_id,
        )
        payload = _json_object(citation)
        payload["resource_uri"] = f"scholens://papers/{parsed.document_id}"
        return ToolOutcome(
            payload=payload,
            artifacts=[_json_object(citation)],
            resource_links=(_paper_link(parsed.document_id, citation.data.title),),
        )

    def get_paper_download_url(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DocumentInput.model_validate(arguments)
        self._require_paper(capabilities, context, parsed.document_id)
        return ToolOutcome(
            payload=_json(
                capabilities.paper_download(
                    actor=context.actor,
                    document_id=parsed.document_id,
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
        return ToolOutcome(
            payload=_json(
                capabilities.projects.list(
                    actor=context.actor,
                    query=parsed.query,
                    sort=parsed.sort,
                    cursor=parsed.cursor,
                    limit=parsed.limit,
                )
            )
        )

    def _project_response(self, project: object) -> wc.ProjectToolResponse:
        parsed = ProjectResponse.model_validate(project)
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
            action={"kind": "project_created", "project": payload},
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
            action={"kind": "project_updated", "project": _json(result)},
            resource_links=(_project_link(result.id, result.title),),
        )

    def delete_project(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DeleteProjectInput.model_validate(arguments)
        project = capabilities.projects.get(
            actor=context.actor, project_id=parsed.project_id
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="delete_project",
            state=project,
            impact=ActionImpact(
                title=f"Delete Project '{project.title}'",
                summary="Permanently delete this Project and its Project-scoped research context.",
                consequences=[
                    f"Remove {project.num_papers} paper associations.",
                    f"Remove {project.num_outputs} Project research outputs.",
                    f"Remove access for {project.num_collaborators} collaborators.",
                ],
                affected_resources=[f"project:{project.id}"],
            ),
        )
        if challenge is not None:
            return challenge
        capabilities.projects.delete(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
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
        return ToolOutcome(
            payload=_json(
                capabilities.projects.documents(
                    actor=context.actor,
                    project_id=parsed.project_id,
                    load_urls=False,
                    query=parsed.query,
                    sort=parsed.sort,
                    cursor=parsed.cursor,
                    limit=parsed.limit,
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
        project = capabilities.projects.get(
            actor=context.actor, project_id=parsed.project_id
        )
        items = capabilities.research_items.list_document(
            actor=context.actor,
            document_id=parsed.document_id,
            project_id=parsed.project_id,
        ).items
        project_threads = [
            item
            for item in items
            if item.kind is ResearchItemKind.ANNOTATION_THREAD
            and getattr(item.audience, "project_id", None) == parsed.project_id
        ]
        comment_count = sum(
            len(item.annotation_thread.comments)
            for item in project_threads
            if item.annotation_thread is not None
        )
        state = {"project": project, "threads": project_threads}
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="remove_paper_from_project",
            state=state,
            impact=ActionImpact(
                title="Remove paper from Project",
                summary=f"Remove this paper from '{project.title}'.",
                consequences=[
                    f"Delete {len(project_threads)} Project annotation threads and {comment_count} comments anchored to this paper."
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
                _project_link(parsed.project_id, project.title),
                _paper_link(parsed.document_id),
            ),
        )

    def list_paper_projects(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DocumentInput.model_validate(arguments)
        self._require_paper(capabilities, context, parsed.document_id)
        return ToolOutcome(
            payload=_json(
                capabilities.projects.projects_for_document(
                    actor=context.actor, document_id=parsed.document_id
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
        parsed = wc.ProjectInput.model_validate(arguments)
        return ToolOutcome(
            payload=_json(
                capabilities.projects.members(
                    actor=context.actor, project_id=parsed.project_id
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
        parsed = wc.ProjectInput.model_validate(arguments)
        return ToolOutcome(
            payload=_json(
                capabilities.projects.invitations(
                    actor=context.actor, project_id=parsed.project_id
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
        members = capabilities.projects.members(
            actor=context.actor, project_id=parsed.project_id
        )
        target = next(
            (item for item in members.items if item.user_id == parsed.user_id), None
        )
        if target is None:
            raise AppError(
                code="project_member_not_found",
                message="Project member not found",
                kind=FailureKind.NOT_FOUND,
            )
        requested = wc.project_permission_set(
            edit_project=parsed.edit_project,
            manage_papers=parsed.manage_papers,
            manage_collaborators=parsed.manage_collaborators,
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="update_project_member",
            state=target,
            impact=ActionImpact(
                title="Change Project member permissions",
                summary=f"Change permissions for {target.email} in '{project.title}'.",
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
            result=result,
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
        members = capabilities.projects.members(
            actor=context.actor, project_id=parsed.project_id
        )
        target = next(
            (item for item in members.items if item.user_id == parsed.user_id), None
        )
        if target is None:
            raise AppError(
                code="project_member_not_found",
                message="Project member not found",
                kind=FailureKind.NOT_FOUND,
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="remove_project_member",
            state=target,
            impact=ActionImpact(
                title="Remove Project member",
                summary=f"Remove {target.email} from '{project.title}'.",
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
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="leave_project",
            state=project,
            impact=ActionImpact(
                title="Leave Project",
                summary=f"Remove the current user from '{project.title}'.",
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
        project = capabilities.projects.get(
            actor=context.actor, project_id=parsed.project_id
        )
        members = capabilities.projects.members(
            actor=context.actor, project_id=parsed.project_id
        )
        target = next(
            (item for item in members.items if item.user_id == parsed.new_owner_id),
            None,
        )
        if target is None:
            raise AppError(
                code="project_member_not_found",
                message="The new owner must be an existing Project member",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="transfer_project_ownership",
            state={"project": project, "target": target},
            impact=ActionImpact(
                title="Transfer Project ownership",
                summary=f"Make {target.email} the owner of '{project.title}'.",
                consequences=[
                    "The current owner becomes a collaborator and loses owner-only control.",
                    "Quota ownership for Project papers and active ingestions moves to the new owner.",
                ],
                affected_resources=[
                    f"project:{parsed.project_id}",
                    f"user:{parsed.new_owner_id}",
                ],
            ),
        )
        if challenge is not None:
            return challenge
        result = capabilities.projects.transfer(
            actor=context.actor,
            operation=context.operation,
            project_id=parsed.project_id,
            request=ProjectTransferRequest(new_owner_id=parsed.new_owner_id),
        )
        return self._completed(
            action="project_ownership_transferred",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"user:{parsed.new_owner_id}",
            ],
            result=result,
            links=(_project_link(parsed.project_id, project.title),),
        )

    async def create_project_invitation(
        self, context: ToolExecutionContext, arguments: BaseModel, invocation_key: str
    ) -> ToolOutcome:
        del invocation_key
        parsed = wc.CreateProjectInvitationInput.model_validate(arguments)

        def execute(
            capabilities: ApplicationCapabilities,
        ) -> ToolOutcome | ProjectInvitationResponse:
            project = capabilities.projects.get(
                actor=context.actor, project_id=parsed.project_id
            )
            state = {
                "project": project,
                "email": str(parsed.email),
                "permissions": {
                    "edit_project": parsed.edit_project,
                    "manage_papers": parsed.manage_papers,
                    "manage_collaborators": parsed.manage_collaborators,
                },
            }
            challenge = self._confirmation(
                capabilities,
                context,
                parsed,
                action="create_project_invitation",
                state=state,
                impact=ActionImpact(
                    title="Invite Project collaborator",
                    summary=f"Email an invitation to {parsed.email} for '{project.title}'.",
                    consequences=[
                        f"Granted permissions after acceptance: {state['permissions']}"
                    ],
                    affected_resources=[
                        f"project:{parsed.project_id}",
                        f"email:{parsed.email}",
                    ],
                ),
            )
            if challenge is not None:
                return challenge
            return capabilities.projects.create_invitation(
                actor=context.actor,
                operation=context.operation,
                project_id=parsed.project_id,
                request=ProjectInvitationCreateRequest(
                    email=parsed.email,
                    edit_project=parsed.edit_project,
                    manage_papers=parsed.manage_papers,
                    manage_collaborators=parsed.manage_collaborators,
                ),
            )

        outcome = await asyncio.to_thread(self._executor.command, execute)
        if isinstance(outcome, ToolOutcome):
            return outcome
        return self._completed(
            action="project_invitation_created",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"invitation:{outcome.id}",
            ],
            result={
                "invitation": _json(outcome),
                "email_delivery": str(outcome.delivery_status),
            },
            guidance=(
                "Email delivery is queued. Check list_project_invitations for "
                "sent or failed status."
            ),
            links=(_project_link(parsed.project_id, outcome.project_name),),
        )

    async def resend_project_invitation(
        self, context: ToolExecutionContext, arguments: BaseModel, invocation_key: str
    ) -> ToolOutcome:
        del invocation_key
        parsed = wc.InvitationInput.model_validate(arguments)

        def execute(
            capabilities: ApplicationCapabilities,
        ) -> ToolOutcome | ProjectInvitationResponse:
            project = capabilities.projects.get(
                actor=context.actor, project_id=parsed.project_id
            )
            invitation = next(
                (
                    item
                    for item in capabilities.projects.invitations(
                        actor=context.actor, project_id=parsed.project_id
                    ).items
                    if item.id == parsed.invitation_id
                ),
                None,
            )
            if invitation is None:
                raise AppError(
                    code="project_invitation_not_found",
                    message="Project invitation not found",
                    kind=FailureKind.NOT_FOUND,
                )
            challenge = self._confirmation(
                capabilities,
                context,
                parsed,
                action="resend_project_invitation",
                state=invitation,
                impact=ActionImpact(
                    title="Resend Project invitation",
                    summary=f"Invalidate the old token and email a new invitation to {invitation.email} for '{project.title}'.",
                    consequences=[
                        "Previously delivered invitation links stop working."
                    ],
                    affected_resources=[
                        f"project:{parsed.project_id}",
                        f"invitation:{parsed.invitation_id}",
                    ],
                ),
            )
            if challenge is not None:
                return challenge
            return capabilities.projects.resend_invitation(
                actor=context.actor,
                operation=context.operation,
                project_id=parsed.project_id,
                invitation_id=parsed.invitation_id,
            )

        outcome = await asyncio.to_thread(self._executor.command, execute)
        if isinstance(outcome, ToolOutcome):
            return outcome
        return self._completed(
            action="project_invitation_resent",
            affected_resources=[
                f"project:{parsed.project_id}",
                f"invitation:{outcome.id}",
            ],
            result={
                "invitation": _json(outcome),
                "email_delivery": str(outcome.delivery_status),
            },
            guidance=(
                "Email delivery is queued. Check list_project_invitations for "
                "sent or failed status."
            ),
            links=(_project_link(parsed.project_id, outcome.project_name),),
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
        invitation = next(
            (
                item
                for item in capabilities.projects.invitations(
                    actor=context.actor, project_id=parsed.project_id
                ).items
                if item.id == parsed.invitation_id
            ),
            None,
        )
        if invitation is None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                kind=FailureKind.NOT_FOUND,
            )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="revoke_project_invitation",
            state=invitation,
            impact=ActionImpact(
                title="Revoke Project invitation",
                summary=f"Invalidate the invitation for {invitation.email} to '{project.title}'.",
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
        return ToolOutcome(
            payload=_json(
                capabilities.paper_library.list(
                    actor=context.actor,
                    query=parsed.query,
                    tag_ids=tuple(parsed.tag_ids),
                    sort=parsed.sort,
                    cursor=parsed.cursor,
                    limit=parsed.limit,
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

    def get_library_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DocumentInput.model_validate(arguments)
        result = capabilities.paper_library.get(
            actor=context.actor, document_id=parsed.document_id
        )
        return ToolOutcome(
            payload=_json(result),
            resource_links=(_paper_link(parsed.document_id, result.document.title),),
        )

    def update_library_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.UpdateLibraryPaperInput.model_validate(arguments)
        result = capabilities.paper_library.update(
            actor=context.actor,
            operation=context.operation,
            document_id=parsed.document_id,
            request=LibraryPaperUpdateRequest(
                status=parsed.status, metadata_overrides=parsed.metadata_overrides
            ),
        )
        return ToolOutcome(
            payload=_json(result),
            action={"kind": "library_paper_updated", "paper": _json(result)},
            resource_links=(_paper_link(parsed.document_id, result.document.title),),
        )

    def remove_library_papers(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.RemoveLibraryPapersInput.model_validate(arguments)
        papers = [
            capabilities.paper_library.get(actor=context.actor, document_id=document_id)
            for document_id in parsed.document_ids
        ]
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="remove_library_papers",
            state=papers,
            impact=ActionImpact(
                title="Remove papers from personal Library",
                summary=f"Remove {len(papers)} Library entries.",
                consequences=[
                    "Project copies remain available through their Projects.",
                    "Personal annotations and unreferenced document storage may be scheduled for deletion.",
                ],
                affected_resources=[
                    f"document:{document_id}" for document_id in parsed.document_ids
                ],
            ),
        )
        if challenge is not None:
            return challenge
        result = capabilities.paper_library.remove_many(
            actor=context.actor,
            operation=context.operation,
            document_ids=parsed.document_ids,
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
            payload=_json(result),
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
        paper = capabilities.paper_library.get(
            actor=context.actor, document_id=parsed.document_id
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="share_library_paper",
            state=paper,
            impact=ActionImpact(
                title="Make Library paper publicly accessible",
                summary=f"Create or retain a public link for '{paper.document.title or paper.document.original_filename}'.",
                consequences=[
                    "Anyone with the link can read and download the paper until it is unshared."
                ],
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
            links=(_paper_link(parsed.document_id, paper.document.title),),
        )

    def unshare_library_paper(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.SharedPaperInput.model_validate(arguments)
        paper = capabilities.paper_library.get(
            actor=context.actor, document_id=parsed.document_id
        )
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="unshare_library_paper",
            state=paper,
            impact=ActionImpact(
                title="Disable public paper link",
                summary=f"Make '{paper.document.title or paper.document.original_filename}' private again.",
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
            links=(_paper_link(parsed.document_id, paper.document.title),),
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
            payload=_json(result),
            action={"kind": "shared_paper_collected", "result": _json(result)},
            resource_links=(_paper_link(result.document_id),),
        )

    def list_library_tags(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del arguments
        return ToolOutcome(
            payload=_json(capabilities.library_tags.list(actor=context.actor))
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
        tag = next(
            (
                item
                for item in capabilities.library_tags.list(actor=context.actor).items
                if item.id == parsed.tag_id
            ),
            None,
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
                summary=f"Delete the tag '{tag.name}'.",
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
        self, context: ToolExecutionContext, arguments: BaseModel, invocation_key: str
    ) -> ToolOutcome:
        parsed = wc.IngestPaperInput.model_validate(arguments)
        idempotency_key = (
            parsed.idempotency_key
            or "tool:" + hashlib.sha256(invocation_key.encode()).hexdigest()
        )
        if parsed.source.kind == "upload":
            result = await self._ingestion.from_upload_session(
                actor=context.actor,
                operation=context.operation,
                upload_id=parsed.source.upload_id,
                project_id=parsed.project_id,
                idempotency_key=idempotency_key,
                ip_address=context.client_ip,
            )
        else:
            value = (
                parsed.source.doi
                if parsed.source.kind == "doi"
                else (
                    parsed.source.arxiv_id
                    if parsed.source.kind == "arxiv"
                    else parsed.source.url
                )
            )
            result = await self._ingestion.from_source(
                actor=context.actor,
                operation=context.operation,
                kind=parsed.source.kind,
                value=value,
                project_id=parsed.project_id,
                idempotency_key=idempotency_key,
                ip_address=context.client_ip,
            )
        links = tuple(
            link
            for link in (
                (
                    _paper_link(result.document_id)
                    if result.document_id is not None
                    else None
                ),
                (
                    _project_link(result.project_id)
                    if result.project_id is not None
                    else None
                ),
            )
            if link is not None
        )
        return ToolOutcome(
            payload=_json(result),
            action={"kind": "paper_ingestion_started", "result": _json(result)},
            resource_links=links,
        )

    async def retry_paper_ingestion(
        self, context: ToolExecutionContext, arguments: BaseModel, invocation_key: str
    ) -> ToolOutcome:
        parsed = wc.RetryPaperIngestionInput.model_validate(arguments)
        result = await self._ingestion.retry(
            actor=context.actor,
            operation=context.operation,
            job_id=parsed.job_id,
            idempotency_key=parsed.idempotency_key
            or "tool:" + hashlib.sha256(invocation_key.encode()).hexdigest(),
        )
        return ToolOutcome(
            payload=_json(result),
            action={"kind": "paper_ingestion_retried", "result": _json(result)},
        )

    async def cancel_paper_ingestion(
        self, context: ToolExecutionContext, arguments: BaseModel, invocation_key: str
    ) -> ToolOutcome:
        del invocation_key
        parsed = wc.CancelPaperIngestionInput.model_validate(arguments)
        job = await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.jobs.get(
                actor=context.actor, job_id=parsed.job_id
            ),
        )
        challenge = await asyncio.to_thread(
            self._executor.command,
            lambda capabilities: self._confirmation(
                capabilities,
                context,
                parsed,
                action="cancel_paper_ingestion",
                state=job,
                impact=ActionImpact(
                    title="Cancel paper ingestion",
                    summary=f"Stop ingestion job {parsed.job_id}.",
                    consequences=[
                        "Processing stops and reserved capacity is released; a completed job cannot be cancelled."
                    ],
                    affected_resources=[f"job:{parsed.job_id}"],
                ),
            ),
        )
        if challenge is not None:
            return challenge
        await self._ingestion.cancel(
            actor=context.actor, operation=context.operation, job_id=parsed.job_id
        )
        return self._completed(
            action="paper_ingestion_cancelled",
            affected_resources=[f"job:{parsed.job_id}"],
        )

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
        return ToolOutcome(
            payload=_json(
                capabilities.jobs.list(
                    actor=context.actor,
                    project_id=parsed.project_id,
                    document_id=parsed.document_id,
                    operation=parsed.operation,
                    active=parsed.active,
                )
            )
        )

    def get_job(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.JobInput.model_validate(arguments)
        return ToolOutcome(
            payload=_json(
                capabilities.jobs.get(actor=context.actor, job_id=parsed.job_id)
            )
        )

    def list_annotation_threads(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ListAnnotationThreadsInput.model_validate(arguments)
        self._require_paper(capabilities, context, parsed.document_id)
        result = capabilities.research_items.list_annotation_threads(
            actor=context.actor,
            document_id=parsed.document_id,
            project_id=parsed.project_id,
            audience=parsed.audience,
            mode=parsed.mode,
            status=parsed.status,
        )
        fingerprint = json.dumps(
            parsed.model_dump(mode="json", exclude={"cursor"}),
            separators=(",", ":"),
            sort_keys=True,
        )
        offset = (
            self._annotation_cursors.decode(
                cursor=parsed.cursor,
                fingerprint=fingerprint,
            )
            if parsed.cursor
            else 0
        )
        page = result.items[offset : offset + parsed.limit]
        consumed = offset + len(page)
        next_cursor = (
            self._annotation_cursors.encode(
                fingerprint=fingerprint,
                offset=consumed,
            )
            if consumed < len(result.items)
            else None
        )
        return ToolOutcome(
            payload=_json(wc.ThreadListOutput(items=page, next_cursor=next_cursor)),
            resource_links=tuple(_thread_link(item.id) for item in page),
        )

    def get_annotation_thread(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.AnnotationThreadInput.model_validate(arguments)
        result = capabilities.research_items.get_annotation_thread(
            actor=context.actor, thread_id=parsed.thread_id
        )
        return ToolOutcome(
            payload=_json(result), resource_links=(_thread_link(parsed.thread_id),)
        )

    def create_annotation_thread(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.CreateAnnotationThreadInput.model_validate(arguments)
        self._require_paper(capabilities, context, parsed.document_id)
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
        payload = wc.ThreadActionOutput(
            thread=result, resource_uri=f"scholens://annotation-threads/{result.id}"
        )
        return ToolOutcome(
            payload=_json(payload),
            action={"kind": "annotation_thread_created", "thread": _json(result)},
            resource_links=(_thread_link(result.id), _paper_link(parsed.document_id)),
        )

    def update_annotation_thread(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.UpdateAnnotationThreadInput.model_validate(arguments)
        result = capabilities.research_items.update_annotation_thread(
            actor=context.actor,
            operation=context.operation,
            thread_id=parsed.thread_id,
            request=UpdateAnnotationThreadRequest(
                color=parsed.color, status=parsed.status
            ),
        )
        payload = wc.ThreadActionOutput(
            thread=result, resource_uri=f"scholens://annotation-threads/{result.id}"
        )
        return ToolOutcome(
            payload=_json(payload),
            action={"kind": "annotation_thread_updated", "thread": _json(result)},
            resource_links=(_thread_link(result.id),),
        )

    def delete_annotation_thread(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.DeleteAnnotationThreadInput.model_validate(arguments)
        thread = capabilities.research_items.get_annotation_thread(
            actor=context.actor, thread_id=parsed.thread_id
        )
        content = thread.annotation_thread
        challenge = self._confirmation(
            capabilities,
            context,
            parsed,
            action="delete_annotation_thread",
            state=thread,
            impact=ActionImpact(
                title="Delete annotation thread",
                summary="Delete this annotation thread and its discussion.",
                consequences=[
                    f"Delete {len(content.comments) if content is not None else 0} comments. Threads with replies from other contributors cannot be deleted."
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
        payload = wc.CommentActionOutput(
            comment=result,
            resource_uri=f"scholens://annotation-threads/{parsed.thread_id}",
        )
        return ToolOutcome(
            payload=_json(payload),
            action={"kind": "annotation_comment_created", "comment": _json(result)},
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
        payload = wc.CommentActionOutput(
            comment=result,
            resource_uri=f"scholens://annotation-threads/{result.thread_id}",
        )
        return ToolOutcome(
            payload=_json(payload),
            action={"kind": "annotation_comment_updated", "comment": _json(result)},
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
        kinds = tuple(kind for kind in parsed.kinds if kind in _OUTPUT_KINDS)
        if parsed.scope.kind == "library":
            library_result = capabilities.paper_library.list_outputs(
                actor=context.actor,
                query=parsed.query,
                kinds=kinds,
                sort=parsed.sort,
                cursor=parsed.cursor,
                limit=parsed.limit,
            )
            output_items: list[LibraryOutputResponse | ResearchItemResponse] = []
            output_items.extend(library_result.items)
            output = wc.ResearchOutputList(
                items=output_items,
                next_cursor=library_result.next_cursor,
                previous_cursor=library_result.previous_cursor,
                total_count=library_result.total_count,
            )
        elif parsed.scope.kind == "project":
            project_result = capabilities.projects.outputs(
                actor=context.actor,
                project_id=parsed.scope.project_id,
                query=parsed.query,
                kinds=kinds,
                sort=parsed.sort,
                cursor=parsed.cursor,
                limit=parsed.limit,
            )
            output_items = []
            output_items.extend(project_result.items)
            output = wc.ResearchOutputList(
                items=output_items,
                next_cursor=project_result.next_cursor,
                previous_cursor=project_result.previous_cursor,
                total_count=project_result.total_count,
            )
        else:
            items = capabilities.research_items.list_document(
                actor=context.actor,
                document_id=parsed.scope.document_id,
                project_id=parsed.scope.project_id,
            ).items
            filtered = [
                item
                for item in items
                if item.kind in _OUTPUT_KINDS and (not kinds or item.kind in kinds)
            ]
            if parsed.query:
                query = parsed.query.casefold()
                filtered = [
                    item
                    for item in filtered
                    if query
                    in json.dumps(
                        item.model_dump(mode="json"), ensure_ascii=False
                    ).casefold()
                ]
            output_items = []
            output_items.extend(filtered[: parsed.limit])
            output = wc.ResearchOutputList(
                items=output_items, total_count=len(filtered)
            )
        links = tuple(
            _output_link(
                entry.item.id if isinstance(entry, LibraryOutputResponse) else entry.id
            )
            for entry in output.items
        )
        return ToolOutcome(payload=_json(output), resource_links=links)

    def get_research_output(
        self,
        capabilities: ApplicationCapabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        parsed = wc.ResearchOutputInput.model_validate(arguments)
        result: ResearchItemResponse = capabilities.research_items.get_item(
            actor=context.actor, item_id=parsed.item_id
        )
        if result.kind not in _OUTPUT_KINDS:
            raise AppError(
                code="research_output_not_found",
                message="The requested item is an annotation thread, not a research output",
                kind=FailureKind.NOT_FOUND,
            )
        return ToolOutcome(
            payload=_json(result), resource_links=(_output_link(parsed.item_id),)
        )


__all__ = ["WorkspaceToolHandlers"]
