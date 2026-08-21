"""PostgreSQL retrieval for user-owned conversation history."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Literal
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.selectable import CTE

from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.database.models import (
    Conversation,
    ConversationResponse,
    ConversationTurn,
    Document,
    Project,
)
from app.modules.conversations.application.contracts.search import (
    ConversationSearchPage,
    ConversationSearchPosition,
    ConversationSearchQuery,
    ConversationSearchResult,
)
from app.modules.conversations.application.title_maintenance import (
    ConversationTitleBackfillResult,
)
from app.modules.conversations.domain import DEFAULT_CONVERSATION_TITLE
from app.llm.conversation_titles import fallback_conversation_title
from app.shared.application import Actor
from app.shared.infrastructure.sql_patterns import literal_contains_pattern

MatchField = Literal["title", "scope", "user_query", "assistant_response"]


def _plain_snippet(content: str | None, query: str, *, limit: int = 220) -> str | None:
    if not content:
        return None
    plain = re.sub(r"<[^>]+>", " ", content)
    plain = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"[`#>*_~|]", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return None
    lowered = plain.casefold()
    terms = [query.casefold(), *query.casefold().split()]
    positions = [lowered.find(term) for term in terms if term]
    positions = [position for position in positions if position >= 0]
    start = max(0, min(positions) - 70) if positions else 0
    end = min(len(plain), start + limit)
    snippet = plain[start:end].strip()
    if start > 0:
        snippet = f"…{snippet}"
    if end < len(plain):
        snippet = f"{snippet}…"
    return snippet


class PostgresConversationSearch:
    """Authorization-first lexical search over the visible conversation path."""

    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _active_turns(*, actor_id: int) -> CTE:
        root = aliased(ConversationTurn, name="active_root_turn")
        active = (
            select(
                root.id.label("turn_id"),
                root.conversation_id.label("conversation_id"),
                root.user_query.label("user_query"),
                root.selected_response_id.label("selected_response_id"),
                root.selected_child_turn_id.label("selected_child_turn_id"),
            )
            .join(Conversation, Conversation.selected_root_turn_id == root.id)
            .where(
                Conversation.user_id == actor_id,
                Conversation.archived_at.is_(None),
            )
            .cte("active_conversation_turns", recursive=True)
        )
        child = aliased(ConversationTurn, name="active_child_turn")
        return active.union_all(
            select(
                child.id,
                child.conversation_id,
                child.user_query,
                child.selected_response_id,
                child.selected_child_turn_id,
            ).join(active, child.id == active.c.selected_child_turn_id)
        )

    def search(
        self,
        *,
        actor: Actor,
        request: ConversationSearchQuery,
    ) -> ConversationSearchPage:
        query = request.query.strip()
        normalized = query.casefold()
        contains_pattern = literal_contains_pattern(normalized)
        text_query = func.websearch_to_tsquery("pg_catalog.simple", query)
        active = self._active_turns(actor_id=actor.id)
        scope_label = func.coalesce(
            Project.title,
            Document.title,
            Conversation.scope_label_snapshot,
            "",
        )
        title_text = func.lower(Conversation.title)
        title_contains = title_text.like(contains_pattern, escape="\\")
        project_scope_text = func.lower(func.coalesce(Project.title, ""))
        document_scope_text = func.lower(func.coalesce(Document.title, ""))
        snapshot_scope_text = func.lower(
            func.coalesce(Conversation.scope_label_snapshot, "")
        )
        scope_contains = or_(
            project_scope_text.like(contains_pattern, escape="\\"),
            document_scope_text.like(contains_pattern, escape="\\"),
            snapshot_scope_text.like(contains_pattern, escape="\\"),
        )
        title_similarity = func.similarity(title_text, normalized)
        scope_similarity = func.greatest(
            func.similarity(project_scope_text, normalized),
            func.similarity(document_scope_text, normalized),
            func.similarity(snapshot_scope_text, normalized),
        )

        metadata_rows = self._db.execute(
            select(
                Conversation.id,
                Conversation.title,
                scope_label.label("scope_label"),
                title_contains.label("title_contains"),
                scope_contains.label("scope_contains"),
                title_similarity.label("title_similarity"),
                scope_similarity.label("scope_similarity"),
            )
            .outerjoin(Project, Project.id == Conversation.project_id)
            .outerjoin(Document, Document.id == Conversation.document_id)
            .where(
                Conversation.user_id == actor.id,
                Conversation.archived_at.is_(None),
                or_(
                    title_contains,
                    scope_contains,
                    title_similarity >= 0.12,
                    scope_similarity >= 0.12,
                ),
            )
            .order_by(
                case((title_text == normalized, 0), (title_contains, 1), else_=2),
                title_similarity.desc(),
                scope_similarity.desc(),
                Conversation.updated_at.desc(),
                Conversation.id,
            )
        ).all()

        user_text = func.coalesce(active.c.user_query, "")
        user_contains = func.lower(user_text).like(contains_pattern, escape="\\")
        user_vector = func.to_tsvector("pg_catalog.simple", user_text)
        user_full_text = user_vector.op("@@")(text_query)
        user_rank = func.ts_rank_cd(user_vector, text_query)
        user_rows = self._db.execute(
            select(
                active.c.conversation_id,
                active.c.user_query,
                user_contains.label("contains"),
                user_rank.label("rank"),
            )
            .where(or_(user_contains, user_full_text))
            .order_by(user_contains.desc(), user_rank.desc(), active.c.conversation_id)
        ).all()

        assistant_text = func.coalesce(ConversationResponse.content, "")
        assistant_contains = func.lower(assistant_text).like(
            contains_pattern,
            escape="\\",
        )
        assistant_vector = func.to_tsvector("pg_catalog.simple", assistant_text)
        assistant_full_text = assistant_vector.op("@@")(text_query)
        assistant_rank = func.ts_rank_cd(assistant_vector, text_query)
        assistant_rows = self._db.execute(
            select(
                active.c.conversation_id,
                ConversationResponse.content,
                assistant_contains.label("contains"),
                assistant_rank.label("rank"),
            )
            .join(
                ConversationResponse,
                ConversationResponse.id == active.c.selected_response_id,
            )
            .where(
                ConversationResponse.content.isnot(None),
                or_(assistant_contains, assistant_full_text),
            )
            .order_by(
                assistant_contains.desc(),
                assistant_rank.desc(),
                active.c.conversation_id,
            )
        ).all()

        scores: defaultdict[UUID, float] = defaultdict(float)
        best_matches: dict[UUID, tuple[float, MatchField, str | None]] = {}

        def record(
            conversation_id: UUID,
            *,
            score: float,
            field: MatchField,
            snippet: str | None,
        ) -> None:
            scores[conversation_id] = max(scores[conversation_id], score)
            current = best_matches.get(conversation_id)
            if current is None or score > current[0]:
                best_matches[conversation_id] = (score, field, snippet)

        for row in metadata_rows:
            title_exact = row.title.casefold() == normalized
            if title_exact or row.title_contains or row.title_similarity >= 0.12:
                score = 40.0 if title_exact else 35.0 if row.title_contains else 30.0
                score += float(row.title_similarity or 0)
                record(row.id, score=score, field="title", snippet=None)
            if row.scope_contains or row.scope_similarity >= 0.12:
                score = 25.0 if row.scope_contains else 20.0
                score += float(row.scope_similarity or 0)
                record(
                    row.id,
                    score=score,
                    field="scope",
                    snippet=row.scope_label or None,
                )

        for row in user_rows:
            score = 15.0 + (0.5 if row.contains else 0) + float(row.rank or 0)
            record(
                row.conversation_id,
                score=score,
                field="user_query",
                snippet=_plain_snippet(row.user_query, query),
            )

        for row in assistant_rows:
            score = 10.0 + (0.4 if row.contains else 0) + float(row.rank or 0)
            record(
                row.conversation_id,
                score=score,
                field="assistant_response",
                snippet=_plain_snippet(row.content, query),
            )

        if not scores:
            return ConversationSearchPage(items=[], total=0)

        conversations = list(
            self._db.scalars(
                select(Conversation).where(Conversation.id.in_(scores))
            ).all()
        )
        by_id = {conversation.id: conversation for conversation in conversations}
        ranked_ids = sorted(
            by_id,
            key=lambda conversation_id: (
                -scores[conversation_id],
                -by_id[conversation_id].updated_at.timestamp(),
                str(conversation_id),
            ),
        )
        if request.position is not None:
            position_key = (
                -request.position.score,
                -request.position.updated_at.timestamp(),
                str(request.position.conversation_id),
            )
            ranked_ids = [
                conversation_id
                for conversation_id in ranked_ids
                if (
                    -scores[conversation_id],
                    -by_id[conversation_id].updated_at.timestamp(),
                    str(conversation_id),
                )
                > position_key
            ]
        page_ids = ranked_ids[: request.limit]
        items: list[ConversationSearchResult] = []
        for conversation_id in page_ids:
            _score, matched_field, snippet = best_matches[conversation_id]
            items.append(
                ConversationSearchResult(
                    conversation=conversation_repository.summarize(
                        self._db,
                        conversation=by_id[conversation_id],
                    ),
                    matched_field=matched_field,
                    snippet=snippet,
                )
            )
        next_position = None
        if len(ranked_ids) > request.limit and page_ids:
            last_id = page_ids[-1]
            next_position = ConversationSearchPosition(
                score=scores[last_id],
                updated_at=by_id[last_id].updated_at,
                conversation_id=last_id,
            )
        return ConversationSearchPage(
            items=items,
            total=len(by_id),
            next_position=next_position,
        )


@dataclass(slots=True)
class SqlConversationTitleBackfill:
    db: Session

    def backfill(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> ConversationTitleBackfillResult:
        filters = (
            Conversation.title == DEFAULT_CONVERSATION_TITLE,
            Conversation.selected_root_turn_id.isnot(None),
        )
        candidates = int(
            self.db.scalar(select(func.count(Conversation.id)).where(*filters)) or 0
        )
        rows = self.db.execute(
            select(Conversation, ConversationTurn.user_query)
            .join(
                ConversationTurn,
                ConversationTurn.id == Conversation.selected_root_turn_id,
            )
            .where(*filters)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .limit(batch_size)
        ).all()
        if apply:
            for conversation, user_query in rows:
                conversation.title = fallback_conversation_title(user_query)
            self.db.flush()
        return ConversationTitleBackfillResult(
            candidates=candidates,
            updated_conversations=len(rows) if apply else 0,
        )
