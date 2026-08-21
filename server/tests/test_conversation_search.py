from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.bootstrap.adapters.conversation_search import (
    PostgresConversationSearch,
    _plain_snippet,
)
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.database.models import Conversation
from app.modules.conversations.application.contracts.conversations import (
    ConversationCapabilitiesResponse,
    ConversationSummaryResponse,
)
from app.modules.conversations.application.contracts.search import (
    ConversationSearchQuery,
    ConversationSearchPage,
    ConversationSearchPosition,
    ConversationSearchRequest,
    ConversationSearchResult,
)
from app.modules.conversations.application.search import (
    ConversationSearchCursorCodec,
    SearchConversations,
)
from app.shared.application import Actor
from app.shared.domain import AppError
from app.shared.domain.enums import ConversationScopeType
from app.shared.infrastructure.sql_patterns import literal_contains_pattern


def _actor(user_id: int = 73) -> Actor:
    return Actor(
        id=user_id,
        email=f"reader-{user_id}@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def _summary(conversation_id: uuid.UUID, title: str) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        id=conversation_id,
        title=title,
        updated_at=datetime.now(timezone.utc),
        scope_type=ConversationScopeType.GLOBAL,
        scope_id=None,
        scope_label=None,
        scope_access="active",
        read_only=False,
        read_only_reason=None,
        pinned_at=None,
        archived_at=None,
        capabilities=ConversationCapabilitiesResponse(
            move=True,
            detach=False,
            send=True,
        ),
    )


def test_search_cursor_is_bound_to_actor_query_and_page_size() -> None:
    conversation_id = uuid.uuid4()
    port = MagicMock()
    now = datetime.now(timezone.utc)
    port.search.return_value = ConversationSearchPage(
        items=[
            ConversationSearchResult(
                conversation=_summary(conversation_id, "Memory agents"),
                matched_field="title",
            )
        ],
        total=2,
        next_position=ConversationSearchPosition(
            score=40,
            updated_at=now,
            conversation_id=conversation_id,
        ),
    )
    service = SearchConversations(
        port,
        ConversationSearchCursorCodec("conversation-search-secret"),
    )
    first = service(
        actor=_actor(),
        request=ConversationSearchRequest(query="memory", limit=1),
    )

    assert first.next_cursor is not None
    service(
        actor=_actor(),
        request=ConversationSearchRequest(
            query="memory",
            limit=1,
            cursor=first.next_cursor,
        ),
    )
    assert (
        port.search.call_args.kwargs["request"].position.conversation_id
        == conversation_id
    )

    with pytest.raises(AppError) as changed_query:
        service(
            actor=_actor(),
            request=ConversationSearchRequest(
                query="retrieval",
                limit=1,
                cursor=first.next_cursor,
            ),
        )
    assert changed_query.value.code == "conversation_search_cursor_expired"

    with pytest.raises(AppError):
        service(
            actor=_actor(74),
            request=ConversationSearchRequest(
                query="memory",
                limit=1,
                cursor=first.next_cursor,
            ),
        )


def test_active_path_query_is_authorized_and_follows_only_selected_branches() -> None:
    active = PostgresConversationSearch._active_turns(actor_id=73)
    statement = str(
        active.select().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "conversations.user_id = 73" in statement
    assert "conversations.archived_at IS NULL" in statement
    assert "conversations.selected_root_turn_id" in statement
    assert "selected_child_turn_id" in statement


@pytest.mark.parametrize(
    ("query", "pattern"),
    [
        ("memory", "%memory%"),
        ("100%", "%100\\%%"),
        ("a_b", "%a\\_b%"),
        (r"a\\b", r"%a\\\\b%"),
    ],
)
def test_conversation_search_treats_like_metacharacters_as_literal(
    query: str,
    pattern: str,
) -> None:
    assert literal_contains_pattern(query) == pattern


def test_postgres_search_applies_literal_like_pattern_to_every_text_field() -> None:
    db = MagicMock(spec=Session)
    db.execute.return_value.all.return_value = []
    db.scalars.return_value.all.return_value = []

    PostgresConversationSearch(db).search(
        actor=_actor(),
        request=ConversationSearchQuery(query="100%_\\", limit=10),
    )

    statements = [call.args[0] for call in db.execute.call_args_list]
    assert len(statements) == 3
    for statement in statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        assert " ESCAPE '\\\\'" in str(compiled)
        assert "%100\\%\\_\\\\%" in compiled.params.values()


def test_postgres_search_ranks_metadata_before_messages_and_returns_plain_snippets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    title_id, scope_id, user_id, assistant_id = (uuid.uuid4() for _ in range(4))
    conversations = [
        Conversation(
            id=conversation_id,
            title=title,
            user_id=73,
            scope_type="global",
            updated_at=now - timedelta(minutes=index),
        )
        for index, (conversation_id, title) in enumerate(
            [
                (title_id, "Memory agents"),
                (scope_id, "Project notes"),
                (user_id, "Question"),
                (assistant_id, "Answer"),
            ]
        )
    ]
    db = MagicMock(spec=Session)
    result = MagicMock()
    result.all.side_effect = [
        [
            SimpleNamespace(
                id=title_id,
                title="Memory agents",
                scope_label="",
                title_contains=True,
                scope_contains=False,
                title_similarity=1.0,
                scope_similarity=0.0,
            ),
            SimpleNamespace(
                id=scope_id,
                title="Project notes",
                scope_label="Memory lab",
                title_contains=False,
                scope_contains=True,
                title_similarity=0.0,
                scope_similarity=1.0,
            ),
        ],
        [
            SimpleNamespace(
                conversation_id=user_id,
                user_query="How does memory retrieval work?",
                contains=True,
                rank=0.1,
            )
        ],
        [
            SimpleNamespace(
                conversation_id=assistant_id,
                content="The assistant explains memory retrieval.",
                contains=True,
                rank=0.1,
            )
        ],
    ]
    db.execute.return_value = result
    scalar_result = MagicMock()
    scalar_result.all.return_value = conversations
    db.scalars.return_value = scalar_result
    by_id = {conversation.id: conversation for conversation in conversations}
    monkeypatch.setattr(
        conversation_repository,
        "summarize",
        lambda _db, *, conversation: _summary(
            conversation.id, by_id[conversation.id].title
        ),
    )

    response = PostgresConversationSearch(db).search(
        actor=_actor(),
        request=ConversationSearchQuery(query="memory", limit=10),
    )

    assert response.total == 4
    assert [item.matched_field for item in response.items] == [
        "title",
        "scope",
        "user_query",
        "assistant_response",
    ]
    assert response.items[2].snippet == "How does memory retrieval work?"
    assert "assistant explains memory" in (response.items[3].snippet or "")
    assert _plain_snippet("**Memory**\nresponse", "memory") == "Memory response"
