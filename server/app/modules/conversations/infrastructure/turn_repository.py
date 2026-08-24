"""Persistence for branched conversation turns and generated responses."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from app.database.models import Conversation, ConversationResponse, ConversationTurn
from app.helpers.postgres import sanitize_for_postgres
from app.modules.conversations.application.contracts.trace import ConversationTrace
from app.shared.domain import AppError, FailureKind, JsonValue
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased, contains_eager, selectinload

GenerationKind = Literal["initial", "retry", "branch"]


class TurnRepository:
    def lock_conversation(
        self, db: Session, *, conversation_id: UUID, user_id: int
    ) -> Conversation:
        conversation = db.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
            .with_for_update()
        )
        if conversation is None:
            raise AppError(
                code="conversation_not_found",
                message="Conversation not found",
                kind=FailureKind.NOT_FOUND,
            )
        return conversation

    def require_turn(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        user_id: int,
        lock: bool = False,
    ) -> ConversationTurn:
        statement = (
            select(ConversationTurn)
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                ConversationTurn.id == turn_id,
                ConversationTurn.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if lock:
            statement = statement.with_for_update()
        turn = db.scalar(statement)
        if turn is None:
            raise AppError(
                code="conversation_turn_not_found",
                message="Conversation turn not found",
                kind=FailureKind.NOT_FOUND,
            )
        return turn

    def _all_turns(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        include_research_items: bool = False,
    ) -> tuple[Conversation, list[ConversationTurn]]:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise AppError(
                code="conversation_not_found",
                message="Conversation not found",
                kind=FailureKind.NOT_FOUND,
            )
        response_load = selectinload(ConversationTurn.responses)
        if include_research_items:
            response_load = response_load.selectinload(
                ConversationResponse.research_items
            )
        turns = list(
            db.scalars(
                select(ConversationTurn)
                .options(response_load)
                .where(ConversationTurn.conversation_id == conversation_id)
                .order_by(ConversationTurn.depth, ConversationTurn.branch_index)
            ).all()
        )
        return conversation, turns

    @staticmethod
    def _follow_active_path(
        conversation: Conversation,
        turns: list[ConversationTurn],
    ) -> list[ConversationTurn]:
        by_id = {turn.id: turn for turn in turns}
        current_id = conversation.selected_root_turn_id
        path: list[ConversationTurn] = []
        visited: set[UUID] = set()
        while current_id is not None:
            if current_id in visited:
                raise RuntimeError("conversation branch contains a cycle")
            visited.add(current_id)
            turn = by_id.get(current_id)
            if turn is None or turn.conversation_id != conversation.id:
                raise RuntimeError("conversation branch selector is invalid")
            if path and turn.parent_turn_id != path[-1].id:
                raise RuntimeError("conversation branch is not contiguous")
            if not path and turn.parent_turn_id is not None:
                raise RuntimeError("conversation root selector is not a root turn")
            path.append(turn)
            current_id = turn.selected_child_turn_id
        return path

    def active_path(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        include_research_items: bool = False,
    ) -> tuple[Conversation, list[ConversationTurn]]:
        conversation, turns = self._all_turns(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            include_research_items=include_research_items,
        )
        return conversation, self._follow_active_path(conversation, turns)

    def active_leaf_id(
        self, db: Session, *, conversation_id: UUID, user_id: int
    ) -> UUID | None:
        _, path = self.active_path(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return path[-1].id if path else None

    def branch_groups(
        self,
        db: Session,
        *,
        conversation_id: UUID,
    ) -> dict[UUID | None, list[UUID]]:
        groups: dict[UUID | None, list[tuple[int, UUID]]] = defaultdict(list)
        rows = db.execute(
            select(
                ConversationTurn.id,
                ConversationTurn.parent_turn_id,
                ConversationTurn.branch_index,
            )
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.branch_index)
        ).all()
        for turn_id, parent_turn_id, branch_index in rows:
            groups[parent_turn_id].append((branch_index, turn_id))
        return {
            parent_turn_id: [turn_id for _, turn_id in siblings]
            for parent_turn_id, siblings in groups.items()
        }

    def _running_response_id(
        self, db: Session, *, conversation_id: UUID
    ) -> UUID | None:
        return db.scalar(
            select(ConversationResponse.id)
            .join(ConversationTurn, ConversationTurn.id == ConversationResponse.turn_id)
            .where(
                ConversationTurn.conversation_id == conversation_id,
                ConversationResponse.status == "running",
            )
            .limit(1)
        )

    def create_turn(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        user_id: int,
        created_operation_id: UUID,
        correlation_id: UUID,
        user_query: str,
        contexts: list[dict[str, JsonValue]],
        paper_context: dict[str, JsonValue],
        reasoning_level: str,
        locale: str,
        time_zone: str,
        branch_from_turn_id: UUID | None = None,
    ) -> tuple[ConversationTurn, bool]:
        conversation = self.lock_conversation(
            db, conversation_id=conversation_id, user_id=user_id
        )
        existing = db.scalar(
            select(ConversationTurn).where(
                ConversationTurn.id == turn_id,
                ConversationTurn.conversation_id == conversation_id,
            )
        )
        normalized_query = sanitize_for_postgres(user_query)
        normalized_contexts = sanitize_for_postgres(contexts)
        normalized_paper_context = sanitize_for_postgres(paper_context)
        if existing is not None:
            _, active_path = self.active_path(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            if branch_from_turn_id is not None:
                replay_source = self.require_turn(
                    db,
                    conversation_id=conversation_id,
                    turn_id=branch_from_turn_id,
                    user_id=user_id,
                    lock=True,
                )
                expected_parent_turn_id = replay_source.parent_turn_id
                expected_depth = replay_source.depth
                position_matches = (
                    existing.id != replay_source.id
                    and existing.parent_turn_id == expected_parent_turn_id
                    and existing.depth == expected_depth
                    and bool(active_path and active_path[-1].id == existing.id)
                )
            else:
                expected_parent_turn_id = existing.parent_turn_id
                expected_depth = existing.depth
                position_matches = bool(
                    active_path and active_path[-1].id == existing.id
                )

            immutable_inputs_match = (
                existing.user_query == normalized_query
                and existing.contexts == normalized_contexts
                and existing.paper_context == normalized_paper_context
                and existing.reasoning_level == reasoning_level
                and existing.locale == locale
                and existing.time_zone == time_zone
                and existing.parent_turn_id == expected_parent_turn_id
                and existing.depth == expected_depth
            )
            if not immutable_inputs_match or not position_matches:
                raise AppError(
                    code="conversation_turn_conflict",
                    message="This conversation turn was already used differently",
                    kind=FailureKind.CONFLICT,
                )
            return existing, False

        if self._running_response_id(db, conversation_id=conversation_id) is not None:
            raise AppError(
                code="conversation_response_in_progress",
                message="A response is already being generated for this conversation",
                kind=FailureKind.CONFLICT,
            )

        _, active_path = self.active_path(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        active_ids = {turn.id for turn in active_path}
        source: ConversationTurn | None = None
        if branch_from_turn_id is not None:
            source = self.require_turn(
                db,
                conversation_id=conversation_id,
                turn_id=branch_from_turn_id,
                user_id=user_id,
                lock=True,
            )
            if source.id not in active_ids:
                raise AppError(
                    code="conversation_branch_source_inactive",
                    message="Only a turn on the active branch can be edited",
                    kind=FailureKind.CONFLICT,
                )
            parent_turn_id = source.parent_turn_id
            depth = source.depth
        else:
            parent = active_path[-1] if active_path else None
            parent_turn_id = parent.id if parent is not None else None
            depth = parent.depth + 1 if parent is not None else 1

        sibling_index = db.scalar(
            select(func.max(ConversationTurn.branch_index)).where(
                ConversationTurn.conversation_id == conversation_id,
                (
                    ConversationTurn.parent_turn_id.is_(None)
                    if parent_turn_id is None
                    else ConversationTurn.parent_turn_id == parent_turn_id
                ),
            )
        )
        turn = ConversationTurn(
            id=turn_id,
            conversation_id=conversation_id,
            parent_turn_id=parent_turn_id,
            created_operation_id=created_operation_id,
            correlation_id=correlation_id,
            user_query=normalized_query,
            contexts=normalized_contexts,
            paper_context=normalized_paper_context,
            reasoning_level=reasoning_level,
            locale=locale,
            time_zone=time_zone,
            depth=depth,
            branch_index=(sibling_index or 0) + 1,
        )
        db.add(turn)
        db.flush()

        if parent_turn_id is None:
            conversation.selected_root_turn_id = turn.id
        else:
            parent = self.require_turn(
                db,
                conversation_id=conversation_id,
                turn_id=parent_turn_id,
                user_id=user_id,
                lock=True,
            )
            if source is None:
                if parent.selected_response_id is not None:
                    db.execute(
                        delete(ConversationResponse).where(
                            ConversationResponse.turn_id == parent.id,
                            ConversationResponse.id != parent.selected_response_id,
                        )
                    )
                parent.suggestions = None
            parent.selected_child_turn_id = turn.id

        conversation.path_revision += 1
        conversation.updated_at = datetime.now(timezone.utc)
        db.flush()
        return turn, True

    def create_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        user_id: int,
        created_operation_id: UUID,
        correlation_id: UUID,
        generation_kind: GenerationKind,
    ) -> tuple[ConversationResponse, bool]:
        if generation_kind not in {"initial", "retry", "branch"}:
            raise ValueError("unsupported conversation response generation kind")
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        turn = self.require_turn(
            db,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=user_id,
            lock=True,
        )
        existing = db.get(ConversationResponse, response_id)
        if existing is not None:
            if existing.turn_id != turn.id:
                raise AppError(
                    code="conversation_response_conflict",
                    message="Response identifier already belongs to another turn",
                    kind=FailureKind.CONFLICT,
                )
            return existing, False

        if self._running_response_id(db, conversation_id=conversation_id) is not None:
            raise AppError(
                code="conversation_response_in_progress",
                message="A response is already being generated for this conversation",
                kind=FailureKind.CONFLICT,
            )
        if (
            self.active_leaf_id(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            != turn.id
        ):
            raise AppError(
                code="conversation_response_turn_inactive",
                message="Responses can only be generated for the active branch leaf",
                kind=FailureKind.CONFLICT,
            )

        max_variant = db.scalar(
            select(func.max(ConversationResponse.variant_index)).where(
                ConversationResponse.turn_id == turn.id
            )
        )
        response = ConversationResponse(
            id=response_id,
            turn_id=turn.id,
            created_operation_id=created_operation_id,
            correlation_id=correlation_id,
            variant_index=(max_variant or 0) + 1,
            status="running",
        )
        db.add(response)
        db.flush()
        return response, True

    def complete_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        response_id: UUID,
        user_id: int,
        content: str,
        references: dict[str, JsonValue] | None,
        trace: ConversationTrace | None,
        duration_ms: int,
    ) -> ConversationResponse:
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        response = db.scalar(
            select(ConversationResponse)
            .join(ConversationTurn, ConversationTurn.id == ConversationResponse.turn_id)
            .where(
                ConversationResponse.id == response_id,
                ConversationTurn.conversation_id == conversation_id,
            )
            .with_for_update()
        )
        if response is None:
            raise AppError(
                code="conversation_response_not_found",
                message="Conversation response not found",
                kind=FailureKind.NOT_FOUND,
            )
        if response.status != "running":
            return response
        response.status = "completed"
        response.content = sanitize_for_postgres(content)
        response.references = sanitize_for_postgres(references)
        response.trace = sanitize_for_postgres(
            trace.model_dump(mode="json") if trace is not None else None
        )
        response.duration_ms = max(0, duration_ms)
        response.failure = None
        response.turn.selected_response_id = response.id
        db.flush()
        return response

    def finish_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        response_id: UUID,
        user_id: int,
        status: str,
        duration_ms: int,
        failure: dict[str, JsonValue] | None = None,
    ) -> None:
        if status not in {"failed", "cancelled"}:
            raise ValueError("unfinished responses may only fail or be cancelled")
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        response = db.scalar(
            select(ConversationResponse)
            .join(ConversationTurn, ConversationTurn.id == ConversationResponse.turn_id)
            .where(
                ConversationResponse.id == response_id,
                ConversationTurn.conversation_id == conversation_id,
            )
            .with_for_update()
        )
        if response is not None and response.status == "running":
            response.status = status
            response.duration_ms = max(0, duration_ms)
            response.failure = sanitize_for_postgres(failure)
            response.turn.selected_response_id = response.id
            db.flush()
        elif (
            response is not None
            and response.status == status == "cancelled"
            and duration_ms > (response.duration_ms or 0)
        ):
            response.duration_ms = duration_ms
            db.flush()

    def select_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
        user_id: int,
    ) -> ConversationResponse:
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        turn = self.require_turn(
            db,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=user_id,
            lock=True,
        )
        if (
            self.active_leaf_id(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            != turn.id
        ):
            raise AppError(
                code="conversation_selection_not_active_leaf",
                message="Only the active branch leaf can switch response variants",
                kind=FailureKind.CONFLICT,
            )
        response = db.scalar(
            select(ConversationResponse).where(
                ConversationResponse.id == response_id,
                ConversationResponse.turn_id == turn.id,
                ConversationResponse.status == "completed",
            )
        )
        if response is None:
            raise AppError(
                code="conversation_response_not_selectable",
                message="Conversation response cannot be selected",
                kind=FailureKind.CONFLICT,
            )
        turn.selected_response_id = response.id
        db.flush()
        return response

    def select_branch(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        user_id: int,
    ) -> tuple[Conversation, list[ConversationTurn], bool]:
        conversation = self.lock_conversation(
            db, conversation_id=conversation_id, user_id=user_id
        )
        if self._running_response_id(db, conversation_id=conversation_id) is not None:
            raise AppError(
                code="conversation_response_in_progress",
                message="A branch cannot be switched while a response is running",
                kind=FailureKind.CONFLICT,
            )
        target = self.require_turn(
            db,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=user_id,
            lock=True,
        )
        _, path = self.active_path(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        active_ids = {turn.id for turn in path}
        if target.parent_turn_id is None:
            changed = conversation.selected_root_turn_id != target.id
            conversation.selected_root_turn_id = target.id
        else:
            if target.parent_turn_id not in active_ids:
                raise AppError(
                    code="conversation_branch_parent_inactive",
                    message="The requested branch is not reachable from the active path",
                    kind=FailureKind.CONFLICT,
                )
            parent = self.require_turn(
                db,
                conversation_id=conversation_id,
                turn_id=target.parent_turn_id,
                user_id=user_id,
                lock=True,
            )
            changed = parent.selected_child_turn_id != target.id
            parent.selected_child_turn_id = target.id
        if changed:
            conversation.path_revision += 1
            conversation.updated_at = datetime.now(timezone.utc)
        db.flush()
        selected_conversation, selected_path = self.active_path(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            include_research_items=True,
        )
        return selected_conversation, selected_path, changed

    def require_response(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        response_id: UUID,
        user_id: int,
        lock: bool = False,
    ) -> ConversationResponse:
        statement = (
            select(ConversationResponse)
            .options(selectinload(ConversationResponse.turn))
            .join(ConversationTurn, ConversationTurn.id == ConversationResponse.turn_id)
            .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                ConversationResponse.id == response_id,
                ConversationTurn.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if lock:
            statement = statement.with_for_update()
        response = db.scalar(statement)
        if response is None:
            raise AppError(
                code="conversation_response_not_found",
                message="Conversation response not found",
                kind=FailureKind.NOT_FOUND,
            )
        return response

    def save_suggestions_if_active_leaf(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        user_id: int,
        suggestions: tuple[str, str, str],
    ) -> bool:
        self.lock_conversation(db, conversation_id=conversation_id, user_id=user_id)
        turn = self.require_turn(
            db,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=user_id,
            lock=True,
        )
        if (
            self.active_leaf_id(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            != turn.id
        ):
            return False
        turn.suggestions = list(suggestions)
        db.flush()
        return True

    def list_turns(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        offset: int,
        limit: int,
    ) -> tuple[Conversation, list[ConversationTurn]]:
        conversation, path = self.active_path(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            include_research_items=True,
        )
        end = max(0, len(path) - offset)
        start = max(0, end - limit)
        return conversation, path[start:end]

    def history_before_turn(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: int,
        turn_id: UUID,
    ) -> list[ConversationTurn]:
        ancestry = (
            select(
                ConversationTurn.id.label("turn_id"),
                ConversationTurn.parent_turn_id.label("parent_turn_id"),
            )
            .join(
                Conversation,
                Conversation.id == ConversationTurn.conversation_id,
            )
            .where(
                ConversationTurn.id == turn_id,
                ConversationTurn.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .cte("conversation_ancestry", recursive=True)
        )
        parent = aliased(ConversationTurn)
        # UNION bounds corrupt cycles; the validation below still reports them.
        ancestry = ancestry.union(
            select(
                parent.id,
                parent.parent_turn_id,
            )
            .join(ancestry, parent.id == ancestry.c.parent_turn_id)
            .where(parent.conversation_id == conversation_id)
        )
        selected_response = aliased(ConversationResponse)
        turns = list(
            db.scalars(
                select(ConversationTurn)
                .join(ancestry, ancestry.c.turn_id == ConversationTurn.id)
                .outerjoin(
                    selected_response,
                    selected_response.id == ConversationTurn.selected_response_id,
                )
                .options(
                    contains_eager(
                        ConversationTurn.selected_response,
                        alias=selected_response,
                    )
                )
                .execution_options(populate_existing=True)
            )
            .unique()
            .all()
        )
        by_id = {turn.id: turn for turn in turns}
        target = by_id.get(turn_id)
        if target is None:
            raise AppError(
                code="conversation_turn_not_found",
                message="Conversation turn not found",
                kind=FailureKind.NOT_FOUND,
            )
        ancestors: list[ConversationTurn] = []
        current_id = target.parent_turn_id
        visited: set[UUID] = set()
        while current_id is not None:
            if current_id in visited:
                raise RuntimeError("conversation ancestry contains a cycle")
            visited.add(current_id)
            current = by_id.get(current_id)
            if current is None:
                raise RuntimeError("conversation ancestry is incomplete")
            ancestors.append(current)
            current_id = current.parent_turn_id
        ancestors.reverse()
        return [turn for turn in ancestors if turn.selected_response_id is not None]


turn_repository = TurnRepository()
