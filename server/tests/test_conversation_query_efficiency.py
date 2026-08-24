import uuid
from collections.abc import Iterable
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.bootstrap.adapters.conversation_chat_data import (
    SqlAlchemyConversationChatData,
)
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import (
    ConversationResponse,
    ConversationTurn,
    Document,
    ResearchAudienceType,
    ResearchItem,
    ResearchItemKind,
)
from app.modules.conversations.application.chat import ConversationChatScope
from app.modules.conversations.application.contracts.turns import (
    ConversationTurnCreateRequest,
)
from app.modules.conversations.infrastructure.turn_repository import turn_repository
from app.modules.papers.application.contracts.search import SelectedPaperCollection
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_CHAT_CONTEXT_COLUMNS,
    DocumentColumns,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.application import Actor
from app.shared.domain import AppError, WorkspacePermission
from app.shared.domain.enums import ConversationScopeType
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql import ClauseElement


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def _compiled(statement: ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    ).lower()


def test_find_accessible_many_is_ordered_deduplicated_and_authorized() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    missing_id = uuid.uuid4()
    first = Document(id=first_id)
    second = Document(id=second_id)
    db = MagicMock(spec=Session)
    db.scalars.return_value.all.return_value = [second, first]

    documents = document_repository.find_accessible_many(
        db,
        document_ids=[
            second_id,
            "not-a-uuid",
            missing_id,
            first_id,
            second_id,
        ],
        user=_actor(),
    )

    assert documents == [second, first]
    db.scalars.assert_called_once()
    sql = _compiled(db.scalars.call_args.args[0])
    assert "library_papers" in sql
    assert "project_papers" in sql
    assert "project_collaborators" in sql
    assert "documents.id in" in sql


def test_find_accessible_many_skips_a_query_for_empty_or_invalid_input() -> None:
    db = MagicMock(spec=Session)

    assert (
        document_repository.find_accessible_many(
            db,
            document_ids=[None, "invalid"],
            user=_actor(),
        )
        == []
    )
    db.scalars.assert_not_called()


def test_get_annotation_threads_visible_is_ordered_bounded_and_authorized() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    missing_id = uuid.uuid4()
    first = ResearchItem(
        id=first_id,
        kind=ResearchItemKind.ANNOTATION_THREAD.value,
        created_by_id=_actor().id,
        audience_type=ResearchAudienceType.PERSONAL.value,
        target_document_id=uuid.uuid4(),
    )
    second = ResearchItem(
        id=second_id,
        kind=ResearchItemKind.ANNOTATION_THREAD.value,
        created_by_id=_actor().id,
        audience_type=ResearchAudienceType.PERSONAL.value,
        target_document_id=uuid.uuid4(),
    )
    db = MagicMock(spec=Session)
    db.scalars.return_value.unique.return_value.all.return_value = [second, first]

    items = research_repository.get_annotation_threads_visible(
        db,
        thread_ids=[second_id, missing_id, first_id, second_id],
        user_id=_actor().id,
    )

    assert items == [second, first]
    db.scalars.assert_called_once()
    sql = _compiled(db.scalars.call_args.args[0])
    assert "research_items.id in" in sql
    assert "research_items.kind" in sql
    assert "research_items.audience_type" in sql
    assert "project_collaborators" in sql
    assert "library_papers" in sql


def test_get_annotation_threads_visible_skips_a_query_for_empty_input() -> None:
    db = MagicMock(spec=Session)

    assert (
        research_repository.get_annotation_threads_visible(
            db,
            thread_ids=[],
            user_id=_actor().id,
        )
        == []
    )
    db.scalars.assert_not_called()


def test_context_batches_fifty_document_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_ids = [uuid.uuid4() for _ in range(50)]
    papers = [
        SimpleNamespace(
            id=document_id,
            title=f"Paper {index}",
            abstract=f"Abstract {index}",
            raw_content=f"Content {index}",
            keywords=[],
            authors=[],
            publish_date=None,
        )
        for index, document_id in enumerate(document_ids)
    ]
    batches: list[list[object]] = []

    def find_many(
        _db: Session,
        *,
        document_ids: Iterable[object],
        user: Actor,
        document_columns: DocumentColumns,
    ) -> list[object]:
        assert user.id == _actor().id
        assert document_columns == DOCUMENT_CHAT_CONTEXT_COLUMNS
        batches.append(list(document_ids))
        return papers

    monkeypatch.setattr(document_repository, "find_accessible_many", find_many)
    db = MagicMock(spec=Session)
    db.execute.return_value.all.return_value = []

    snapshot = SqlAlchemyConversationChatData(db).context(
        actor=_actor(),
        scope=ConversationChatScope(
            scope_type=ConversationScopeType.GLOBAL,
            project_id=None,
            document_id=None,
            paper_context=SelectedPaperCollection(document_ids=document_ids),
            tool_permissions=frozenset(WorkspacePermission),
            title_is_default=False,
        ),
    )

    assert len(snapshot.papers) == 50
    assert len(batches) == 1
    assert set(batches[0]) == set(document_ids)


def test_mentions_batch_fifty_threads_and_their_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_ids = [uuid.uuid4() for _ in range(10)]
    thread_ids = [uuid.uuid4() for _ in range(50)]
    items = [
        SimpleNamespace(
            id=thread_id,
            target_document_id=document_ids[index % len(document_ids)],
            annotation_thread=SimpleNamespace(
                quote_text=f"Quote {index}",
                position=None,
                comments=[SimpleNamespace(content=f"Comment {index}")],
            ),
        )
        for index, thread_id in enumerate(thread_ids)
    ]
    papers = [
        SimpleNamespace(
            id=document_id,
            title=f"Paper {index}",
            abstract=f"Abstract {index}",
        )
        for index, document_id in enumerate(document_ids)
    ]
    thread_batches: list[list[uuid.UUID]] = []
    document_batches: list[list[object]] = []

    def get_threads(
        _db: Session,
        *,
        thread_ids: Iterable[uuid.UUID],
        user_id: int,
    ) -> list[object]:
        assert user_id == _actor().id
        thread_batches.append(list(thread_ids))
        return items

    def get_papers(
        _db: Session,
        *,
        document_ids: Iterable[object],
        user: Actor,
    ) -> list[object]:
        assert user.id == _actor().id
        document_batches.append(list(document_ids))
        return papers

    monkeypatch.setattr(
        research_repository,
        "get_annotation_threads_visible",
        get_threads,
    )
    monkeypatch.setattr(document_repository, "find_accessible_many", get_papers)
    request = ConversationTurnCreateRequest.model_validate(
        {
            "turn_id": str(uuid.uuid4()),
            "response_id": str(uuid.uuid4()),
            "user_query": "Compare these annotations",
            "locale": "en",
            "time_zone": "UTC",
            "contexts": [
                {"kind": "annotation_thread", "thread_id": str(thread_id)}
                for thread_id in thread_ids
            ],
        }
    )

    mentions = SqlAlchemyConversationChatData(MagicMock(spec=Session)).mentions(
        actor=_actor(),
        request=request,
    )

    assert mentions.snapshot is not None
    assert len(mentions.snapshot) == 50
    assert len(thread_batches) == 1
    assert thread_batches[0] == thread_ids
    assert len(document_batches) == 1
    assert set(document_batches[0]) == set(document_ids)


def test_history_query_reads_only_the_target_ancestry_in_one_round_trip() -> None:
    conversation_id = uuid.uuid4()
    turns: list[ConversationTurn] = []
    parent_id: uuid.UUID | None = None
    for depth in range(1, 51):
        turn = ConversationTurn(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            parent_turn_id=parent_id,
            depth=depth,
            branch_index=1,
        )
        if depth < 50:
            response = ConversationResponse(
                id=uuid.uuid4(),
                turn_id=turn.id,
                variant_index=2,
                status="completed",
                content=f"Answer {depth}",
            )
            turn.selected_response_id = response.id
            turn.selected_response = response
        turns.append(turn)
        parent_id = turn.id

    db = MagicMock(spec=Session)
    db.scalars.return_value.unique.return_value.all.return_value = list(reversed(turns))

    history = turn_repository.history_before_turn(
        db,
        conversation_id=conversation_id,
        user_id=_actor().id,
        turn_id=turns[-1].id,
    )

    assert [turn.id for turn in history] == [turn.id for turn in turns[:-1]]
    assert all(turn.selected_response is not None for turn in history)
    db.scalars.assert_called_once()
    sql = _compiled(db.scalars.call_args.args[0])
    assert "with recursive conversation_ancestry" in sql
    assert " union select " in " ".join(sql.split())
    assert "conversation_ancestry.parent_turn_id" in sql
    assert "conversations.user_id" in sql
    assert "selected_response_id" in sql


def test_history_query_keeps_missing_turn_authorization_as_not_found() -> None:
    db = MagicMock(spec=Session)
    db.scalars.return_value.unique.return_value.all.return_value = []

    with pytest.raises(AppError) as exc_info:
        turn_repository.history_before_turn(
            db,
            conversation_id=uuid.uuid4(),
            user_id=_actor().id,
            turn_id=uuid.uuid4(),
        )

    assert exc_info.value.code == "conversation_turn_not_found"
    db.scalars.assert_called_once()
