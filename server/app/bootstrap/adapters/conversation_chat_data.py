"""SQLAlchemy adapter for short, snapshot-based chat transactions."""

from __future__ import annotations

import uuid
from typing import Literal, cast

from app.bootstrap.adapters.conversation_access import conversation_policy
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import Conversation
from app.database.models import Document, Project, ProjectPaper
from app.llm.token_credits import has_token_credits
from app.modules.conversations.application.chat import (
    ChatHistoryMessage,
    ChatPaperSnapshot,
    ChatProjectSnapshot,
    ConversationBranchPreparation,
    ConversationContextSnapshot,
    ConversationChatDataGateway,
    ConversationChatScope,
    ConversationTurnCompletion,
    ConversationTurnStart,
    MentionScope,
    PersistedChatResponse,
)
from app.modules.conversations.domain import DEFAULT_CONVERSATION_TITLE
from app.modules.conversations.application.contracts.turns import (
    ConversationTurnBranchCreateRequest,
    ConversationTurnCreateRequest,
)
from app.modules.conversations.application.contracts.conversations import PaperContext
from app.modules.conversations.application.contracts.contexts import (
    AnnotationThreadTurnContext,
)
from app.modules.conversations.application.contracts.trace import ConversationTrace
from app.modules.conversations.infrastructure.turn_repository import turn_repository
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperCollection,
    SelectedPaperCollection,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain import normalize_workspace_permissions
from app.shared.domain.enums import ConversationScopeType
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from pydantic import TypeAdapter


_PAPER_CONTEXT: TypeAdapter[PaperContext] = TypeAdapter(PaperContext)


class SqlAlchemyConversationChatData(ConversationChatDataGateway):
    def __init__(self, session: Session) -> None:
        self._session = session

    def prepare(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        paper_context_snapshot: PaperCollection | None = None,
    ) -> ConversationChatScope:
        if not has_token_credits(self._session, user=actor):
            raise AppError(
                code="token_quota_exceeded",
                message="Your weekly Token Credits are exhausted",
                kind=FailureKind.RATE_LIMITED,
            )
        conversation = self._conversation(actor=actor, conversation_id=conversation_id)
        conversation_policy.require_can_continue(
            self._session,
            conversation=conversation,
        )
        search_collection = paper_context_snapshot or self._paper_collection(
            conversation_repository.paper_context(
                self._session,
                conversation=conversation,
                user_id=actor.id,
            )
        )
        return ConversationChatScope(
            scope_type=ConversationScopeType(conversation.scope_type),
            project_id=conversation.project_id,
            document_id=conversation.document_id,
            paper_context=search_collection,
            tool_permissions=normalize_workspace_permissions(
                conversation.tool_permissions
            ),
            title_is_default=conversation.title == DEFAULT_CONVERSATION_TITLE,
        )

    @staticmethod
    def _paper_collection(paper_context: PaperContext) -> PaperCollection:
        if paper_context.kind == "library":
            return LibraryPaperCollection()
        return SelectedPaperCollection(
            project_ids=paper_context.project_ids,
            document_ids=paper_context.document_ids,
        )

    def context(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
    ) -> ConversationContextSnapshot:
        context = scope.paper_context
        document_ids = (
            set(context.document_ids) if context.kind == "selection" else set()
        )
        if scope.document_id is not None:
            document_ids.add(scope.document_id)
        papers: list[ChatPaperSnapshot] = []
        for document_id in sorted(document_ids, key=str):
            paper = document_repository.find_accessible(
                self._session,
                document_id=document_id,
                user=actor,
            )
            if paper is None:
                continue
            papers.append(
                ChatPaperSnapshot(
                    document_id=paper.id,
                    title=paper.title,
                    abstract=paper.abstract if paper.id == scope.document_id else None,
                    raw_content=(
                        paper.raw_content if paper.id == scope.document_id else None
                    ),
                    keywords=paper.keywords,
                    authors=paper.authors,
                    publish_date=paper.publish_date,
                )
            )

        project_ids = context.project_ids if context.kind == "selection" else []
        project_rows = self._session.execute(
            select(
                Project.id,
                Project.title,
                Project.description,
                func.count(ProjectPaper.document_id),
            )
            .outerjoin(ProjectPaper, ProjectPaper.project_id == Project.id)
            .where(Project.id.in_(project_ids))
            .group_by(Project.id)
            .order_by(Project.id)
        ).all()
        projects = [
            ChatProjectSnapshot(
                project_id=project_id,
                title=title,
                description=description,
                document_count=int(document_count),
            )
            for project_id, title, description, document_count in project_rows
        ]
        available_document_count = (
            int(
                self._session.scalar(
                    select(func.count(Document.id)).where(
                        accessible_document_condition(user_id=actor.id)
                    )
                )
                or 0
            )
            if context.kind == "library"
            else None
        )
        return ConversationContextSnapshot(
            papers=papers,
            projects=projects,
            available_document_count=available_document_count,
        )

    def history(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        before_turn_id: uuid.UUID,
    ) -> list[ChatHistoryMessage]:
        history: list[ChatHistoryMessage] = []
        for turn in turn_repository.history_before_turn(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
            turn_id=before_turn_id,
        ):
            selected = next(
                (
                    response
                    for response in turn.responses
                    if response.id == turn.selected_response_id
                ),
                None,
            )
            if selected is None or selected.content is None:
                continue
            history.append(ChatHistoryMessage(role="user", content=turn.user_query))
            history.append(
                ChatHistoryMessage(role="assistant", content=selected.content)
            )
        return history

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationTurnCreateRequest,
    ) -> MentionScope:
        annotation_contexts = [
            context
            for context in request.contexts
            if isinstance(context, AnnotationThreadTurnContext)
        ]
        if not annotation_contexts:
            return MentionScope(None, None)

        snapshot: list[dict[str, JsonValue]] = []
        annotations_by_paper: dict[str, dict[str, JsonValue]] = {}
        for context in annotation_contexts:
            try:
                item = research_repository.get_annotation_thread_visible(
                    self._session,
                    thread_id=context.thread_id,
                    user_id=actor.id,
                )
            except AppError:
                continue
            thread = item.annotation_thread
            if thread is None or item.target_document_id is None:
                continue
            document_id = str(item.target_document_id)
            group = annotations_by_paper.get(document_id)
            if group is None:
                paper = document_repository.find_accessible(
                    self._session,
                    document_id=document_id,
                    user=actor,
                )
                group = {
                    "document_id": document_id,
                    "paper_title": paper.title if paper else None,
                    "paper_abstract": paper.abstract if paper else None,
                    "annotation_threads": [],
                }
                annotations_by_paper[document_id] = group
            annotations = [
                comment.content for comment in thread.comments if comment.content
            ]
            json_annotations = cast(list[JsonValue], annotations)
            snapshot.append(
                {
                    "kind": "annotation_thread",
                    "id": str(item.id),
                    "title": thread.quote_text,
                    "document_id": document_id,
                    "paper_title": group["paper_title"],
                    "annotations": json_annotations,
                }
            )
            annotation_threads = group["annotation_threads"]
            assert isinstance(annotation_threads, list)
            annotation_threads.append(
                {
                    "quoted_text": thread.quote_text,
                    "position": thread.position,
                    "annotations": json_annotations,
                }
            )
        return MentionScope(
            snapshot=snapshot,
            annotation_threads=list(annotations_by_paper.values()),
        )

    @staticmethod
    def _persisted(response: object) -> PersistedChatResponse:
        from app.modules.conversations.infrastructure.models import ConversationResponse

        if not isinstance(response, ConversationResponse):
            raise TypeError("expected ConversationResponse")
        return PersistedChatResponse(
            id=response.id,
            turn_id=response.turn_id,
            variant_index=response.variant_index,
            status=response.status,
            content=response.content or "",
            references=response.references,
            trace=(
                ConversationTrace.model_validate(response.trace)
                if response.trace is not None
                else None
            ),
            duration_ms=response.duration_ms,
        )

    def start_turn(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
        generation_kind: Literal["initial", "retry", "branch"],
        user_content: str,
        contexts: list[dict[str, JsonValue]],
        paper_context: dict[str, JsonValue],
        reasoning_level: str,
        locale: str,
        time_zone: str,
        branch_from_turn_id: uuid.UUID | None,
        created_operation_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> ConversationTurnStart:
        if generation_kind == "branch":
            conversation_repository.update_paper_context(
                self._session,
                conversation_id=conversation_id,
                user_id=actor.id,
                request=_PAPER_CONTEXT.validate_python(paper_context),
            )
        turn, turn_created = turn_repository.create_turn(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=actor.id,
            created_operation_id=created_operation_id,
            correlation_id=correlation_id,
            user_query=user_content,
            contexts=contexts,
            paper_context=paper_context,
            reasoning_level=reasoning_level,
            locale=locale,
            time_zone=time_zone,
            branch_from_turn_id=branch_from_turn_id,
        )
        response, response_created = turn_repository.create_response(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
            user_id=actor.id,
            created_operation_id=created_operation_id,
            correlation_id=correlation_id,
            generation_kind=generation_kind,
        )
        return ConversationTurnStart(
            turn_id=turn.id,
            response=self._persisted(response),
            turn_operation_id=turn.created_operation_id,
            correlation_id=turn.correlation_id,
            turn_created=turn_created,
            response_created=response_created,
            generation_kind=generation_kind,
            suggestions=tuple(turn.suggestions or ()),
        )

    def complete_turn(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: ConversationTrace | None,
        artifacts: list[dict[str, JsonValue]],
        duration_ms: int,
        created_operation_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> ConversationTurnCompletion:
        conversation = self._conversation(
            actor=actor,
            conversation_id=conversation_id,
        )
        turn = turn_repository.require_turn(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=actor.id,
        )
        if turn.correlation_id != correlation_id:
            raise AppError(
                code="conversation_turn_causality_invalid",
                message="The conversation turn causality is invalid",
                kind=FailureKind.CONFLICT,
            )
        prior_status = next(
            (item.status for item in turn.responses if item.id == response_id),
            None,
        )
        response = turn_repository.complete_response(
            self._session,
            conversation_id=conversation_id,
            response_id=response_id,
            user_id=actor.id,
            content=assistant_content,
            references=assistant_references,
            trace=assistant_trace,
            duration_ms=duration_ms,
        )
        citation_ids: tuple[uuid.UUID, ...] = ()
        if artifacts and prior_status != "completed":
            citation_ids = tuple(
                item.id
                for item in research_repository.create_citations_for_response(
                    self._session,
                    conversation=conversation,
                    response_id=response.id,
                    user_id=actor.id,
                    snapshots=cast(list[dict[str, object]], artifacts),
                )
            )
        return ConversationTurnCompletion(
            response=self._persisted(response),
            created=prior_status != "completed",
            citation_ids=citation_ids,
        )

    def finish_response(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        response_id: uuid.UUID,
        status: str,
        duration_ms: int,
    ) -> None:
        turn_repository.finish_response(
            self._session,
            conversation_id=conversation_id,
            response_id=response_id,
            user_id=actor.id,
            status=status,
            duration_ms=duration_ms,
        )

    def save_turn_suggestions(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        suggestions: tuple[str, str, str],
    ) -> bool:
        return turn_repository.save_suggestions_if_active_leaf(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=actor.id,
            suggestions=suggestions,
        )

    def retry_request(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
    ) -> ConversationTurnCreateRequest:
        turn = turn_repository.require_turn(
            self._session,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=actor.id,
        )
        if (
            turn_repository.active_leaf_id(
                self._session,
                conversation_id=conversation_id,
                user_id=actor.id,
            )
            != turn.id
        ):
            raise AppError(
                code="conversation_retry_not_active_leaf",
                message="Only the active branch leaf can be retried",
                kind=FailureKind.CONFLICT,
            )
        return ConversationTurnCreateRequest.model_validate(
            {
                "turn_id": turn.id,
                "response_id": response_id,
                "user_query": turn.user_query,
                "locale": turn.locale,
                "time_zone": turn.time_zone,
                "contexts": turn.contexts or [],
                "reasoning_level": turn.reasoning_level,
            }
        )

    def branch_request(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
        source_turn_id: uuid.UUID,
        request: ConversationTurnBranchCreateRequest,
    ) -> ConversationBranchPreparation:
        conversation = self._conversation(
            actor=actor,
            conversation_id=conversation_id,
        )
        conversation_policy.require_can_continue(
            self._session,
            conversation=conversation,
        )
        _, active_path = turn_repository.active_path(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
        )
        source = next(
            (turn for turn in active_path if turn.id == source_turn_id),
            None,
        )
        if source is None:
            raise AppError(
                code="conversation_branch_source_inactive",
                message="Only a turn on the active branch can be edited",
                kind=FailureKind.CONFLICT,
            )
        paper_context = _PAPER_CONTEXT.validate_python(source.paper_context)
        conversation_repository.validate_paper_context(
            self._session,
            conversation=conversation,
            user_id=actor.id,
            request=paper_context,
        )
        return ConversationBranchPreparation(
            request=ConversationTurnCreateRequest.model_validate(
                {
                    "turn_id": request.turn_id,
                    "response_id": request.response_id,
                    "user_query": request.user_query,
                    "locale": source.locale,
                    "time_zone": source.time_zone,
                    "contexts": source.contexts or [],
                    "reasoning_level": source.reasoning_level,
                }
            ),
            paper_context=self._paper_collection(paper_context),
        )

    def _conversation(
        self,
        *,
        actor: Actor,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        return conversation_repository.require_owned(
            self._session,
            conversation_id=conversation_id,
            user_id=actor.id,
        )
