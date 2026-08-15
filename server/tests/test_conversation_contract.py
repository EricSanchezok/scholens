import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from app.database.models import (
    Conversation,
    ConversationContextDocument,
    ConversationContextProject,
    ConversationResponse,
    ConversationTurn,
)
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.main import app
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.bootstrap.adapters.conversation_lifecycle import (
    SqlAlchemyConversationGateway,
)
from app.bootstrap.adapters.conversation_chat_data import (
    SqlAlchemyConversationChatData,
)
from app.modules.conversations.application.chat import ConversationChatScope
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationListRequest,
    LibraryPaperContext,
    ConversationMoveRequest,
    SelectedPaperContext,
    ConversationUpdateRequest,
)
from app.modules.conversations.application.conversations import (
    ConversationListPosition,
    ConversationPage,
    ConversationTurnsPage,
    Conversations,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationAssistantItem,
    ConversationTurnBranchCreateRequest,
)
from app.modules.conversations.application.contracts.trace import ConversationTrace
from app.modules.conversations.infrastructure.presenters import serialize_turns
from app.modules.conversations.infrastructure.turn_repository import turn_repository
from app.shared.application import Actor, SignedCursorCodec
from app.modules.operation_journal.application import OperationJournal
from app.shared.domain.enums import ConversationScopeType
from sqlalchemy.orm import Session
from pydantic import ValidationError


def _current_user() -> Actor:
    return Actor(
        id=1,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def test_response_trace_serializes_as_a_typed_product_trace() -> None:
    turn = ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        created_operation_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        user_query="Question",
        contexts=[],
        paper_context={"kind": "library"},
        reasoning_level="standard",
        locale="en",
        time_zone="UTC",
        depth=1,
        branch_index=1,
    )
    response = ConversationResponse(
        id=uuid.uuid4(),
        turn_id=turn.id,
        created_operation_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        variant_index=1,
        status="completed",
        content="Answer",
        references={"annotations": [], "sources": []},
        trace={
            "entries": [
                {
                    "kind": "activity",
                    "id": "search-1",
                    "sequence": 1,
                    "category": "search",
                    "state": "succeeded",
                    "subject": "reasoning compression",
                    "source_count": 2,
                }
            ],
            "citation_summary": {
                "source_count": 2,
                "annotation_count": 1,
                "rejected_source_count": 0,
            },
        },
        duration_ms=1_250,
    )
    response.research_items = []
    turn.responses = [response]
    turn.selected_response_id = response.id

    serialized = serialize_turns(
        [turn],
        active_leaf_id=turn.id,
        branch_groups={None: [turn.id]},
    )

    assert serialized[0].responses[0].trace == ConversationTrace.model_validate(
        response.trace
    )
    assert serialized[0].selected_response_id == response.id
    assert serialized[0].responses[0].duration_ms == 1_250
    assert serialized[0].branch.index == 1
    assert serialized[0].branch.count == 1


def test_completed_assistant_items_require_visible_content() -> None:
    with pytest.raises(ValidationError):
        ConversationAssistantItem(
            id="assistant:item",
            sequence=1,
            phase="final",
            content="",
        )


def test_active_path_follows_persisted_root_and_child_selectors() -> None:
    conversation_id = uuid.uuid4()
    root_one = ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        parent_turn_id=None,
        selected_child_turn_id=None,
        depth=1,
        branch_index=1,
    )
    root_two = ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        parent_turn_id=None,
        depth=1,
        branch_index=2,
    )
    child = ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        parent_turn_id=root_two.id,
        depth=2,
        branch_index=1,
    )
    root_two.selected_child_turn_id = child.id
    conversation = Conversation(
        id=conversation_id,
        selected_root_turn_id=root_two.id,
    )

    path = turn_repository._follow_active_path(  # noqa: SLF001
        conversation,
        [root_one, child, root_two],
    )

    assert [turn.id for turn in path] == [root_two.id, child.id]


def test_turn_serialization_exposes_non_wrapping_prompt_branch_navigation() -> None:
    conversation_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    turn_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    middle = ConversationTurn(
        id=turn_ids[1],
        conversation_id=conversation_id,
        parent_turn_id=parent_id,
        created_operation_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        user_query="Edited prompt",
        contexts=[],
        paper_context={"kind": "library"},
        reasoning_level="standard",
        locale="en",
        time_zone="UTC",
        depth=2,
        branch_index=2,
    )
    middle.responses = []

    serialized = serialize_turns(
        [middle],
        active_leaf_id=middle.id,
        branch_groups={parent_id: turn_ids},
    )

    assert serialized[0].branch.index == 2
    assert serialized[0].branch.count == 3
    assert serialized[0].branch.previous_turn_id == turn_ids[0]
    assert serialized[0].branch.next_turn_id == turn_ids[2]


def test_conversation_scope_contract_is_private_and_unified() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{conversation_id}/scope" in paths
    assert "/api/v1/conversations/{conversation_id}/context" in paths
    assert "/api/v1/conversations/{conversation_id}/turns" in paths
    assert "/api/v1/conversations/{conversation_id}/turns/{turn_id}/responses" in paths
    assert (
        "/api/v1/conversations/{conversation_id}/turns/{turn_id}/selected-response"
        in paths
    )
    assert "/api/v1/conversations/{conversation_id}/selected-branch" in paths
    assert "/api/v1/conversations/{conversation_id}/turns/{turn_id}/branches" in paths
    assert not any(path.endswith("/suggestions") for path in paths)
    assert "/api/v1/conversations/{conversation_id}/messages" not in paths
    assert not any(path.startswith("/api/v1/conversation/") for path in paths)
    assert not any(path.startswith("/api/v1/projects/conversations") for path in paths)
    assert not any("conversation/share" in path for path in paths)

    table = Conversation.__table__
    assert table.c.user_id.nullable is False
    assert table.c.title.nullable is False
    assert {
        "scope_type",
        "paper_context_kind",
        "project_id",
        "document_id",
        "context_deleted_at",
        "pinned_at",
        "archived_at",
        "scope_label_snapshot",
        "selected_root_turn_id",
        "path_revision",
    } <= set(table.c.keys())
    assert "conversable_id" not in table.c
    assert {
        "conversation_id",
        "project_id",
    } <= set(ConversationContextProject.__table__.c.keys())
    assert {
        "conversation_id",
        "document_id",
    } <= set(ConversationContextDocument.__table__.c.keys())
    assert "user_id" not in ConversationTurn.__table__.c
    assert "contexts" in ConversationTurn.__table__.c
    assert "parent_turn_id" in ConversationTurn.__table__.c
    assert "selected_child_turn_id" in ConversationTurn.__table__.c
    assert "paper_context" in ConversationTurn.__table__.c
    assert "depth" in ConversationTurn.__table__.c
    assert "branch_index" in ConversationTurn.__table__.c
    assert "scope" not in ConversationTurn.__table__.c
    assert "sequence" not in ConversationTurn.__table__.c
    assert "user_references" not in ConversationTurn.__table__.c
    assert any(
        constraint.name == "uq_conversation_turns_sibling_branch"
        for constraint in ConversationTurn.__table__.constraints
    )
    assert any(
        constraint.name == "uq_conversation_responses_turn_variant"
        for constraint in ConversationResponse.__table__.constraints
    )


def test_conversation_turns_expose_a_typed_standard_sse_contract() -> None:
    response = app.openapi()["paths"]["/api/v1/conversations/{conversation_id}/turns"][
        "post"
    ]["responses"]["200"]

    assert response["content"]["text/event-stream"]["schema"]["$ref"] == (
        "#/components/schemas/ConversationStreamEventSchema"
    )
    event_schema = app.openapi()["components"]["schemas"][
        "ConversationStreamEventSchema"
    ]["oneOf"]
    assert {item["$ref"].rsplit("/", maxsplit=1)[-1] for item in event_schema} == {
        "ConversationStreamStartEvent",
        "ConversationStreamActivityEvent",
        "ConversationStreamAssistantItemStartEvent",
        "ConversationStreamAssistantItemDeltaEvent",
        "ConversationStreamAssistantItemCompleteEvent",
        "ConversationStreamReferencesEvent",
        "ConversationStreamResponseReadyEvent",
        "ConversationStreamSuggestionsEvent",
        "ConversationStreamCompleteEvent",
        "ConversationStreamErrorEvent",
    }

    schemas = app.openapi()["components"]["schemas"]
    assert "ConversationSuggestionsResponse" not in schemas
    variant_properties = schemas["ConversationResponseVariantResponse"]["properties"]
    assert "suggestions" not in variant_properties
    assert "suggestions_status" not in variant_properties
    assert "suggestions" in schemas["ConversationTurnResponse"]["properties"]
    assert "contexts" in schemas["ConversationTurnResponse"]["properties"]
    assert "paper_context" in schemas["ConversationTurnResponse"]["properties"]
    assert "branch" in schemas["ConversationTurnResponse"]["properties"]
    assert "depth" in schemas["ConversationTurnResponse"]["properties"]
    assert "sequence" not in schemas["ConversationTurnResponse"]["properties"]
    assert "scope" not in schemas["ConversationTurnResponse"]["properties"]
    assert "user_references" not in schemas["ConversationTurnResponse"]["properties"]
    assert "duration_ms" in variant_properties
    create_properties = schemas["ConversationTurnCreateRequest"]["properties"]
    assert "contexts" in create_properties
    assert "mentioned_thread_ids" not in create_properties
    start_generation = schemas["ConversationStreamStartEvent"]["properties"][
        "generation_kind"
    ]
    assert "branch" in start_generation["enum"]


def test_turn_cursor_rejects_a_changed_branch_revision() -> None:
    gateway = MagicMock()
    gateway.turns.return_value = ConversationTurnsPage(items=[], path_revision=4)
    turn_cursors = SignedCursorCodec(
        "test-secret",
        revision="conversation-turns-v3",
        error_code="conversation_cursor_expired",
    )
    service = Conversations(
        gateway=gateway,
        list_cursors=MagicMock(),
        turn_cursors=turn_cursors,
        journal=MagicMock(spec=OperationJournal),
    )
    conversation_id = uuid.uuid4()
    cursor = turn_cursors.encode_keyset(
        fingerprint=f"1:{conversation_id}:20",
        values=("3", "20"),
    )

    with pytest.raises(AppError) as exc_info:
        service.turns(
            actor=_current_user(),
            conversation_id=conversation_id,
            cursor=cursor,
            limit=20,
        )

    assert exc_info.value.code == "conversation_path_changed"


def test_running_response_blocks_another_turn_in_the_same_conversation() -> None:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=1,
        path_revision=2,
    )
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [conversation, None, uuid.uuid4()]

    with pytest.raises(AppError) as exc_info:
        turn_repository.create_turn(
            db,
            conversation_id=conversation.id,
            turn_id=uuid.uuid4(),
            user_id=1,
            created_operation_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            user_query="Another turn",
            contexts=[],
            paper_context={"kind": "library"},
            reasoning_level="standard",
            locale="en",
            time_zone="UTC",
        )

    assert exc_info.value.code == "conversation_response_in_progress"
    db.add.assert_not_called()


def test_branch_request_inherits_source_snapshot_and_reauthorizes_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid.uuid4()
    source = ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        contexts=[{"kind": "annotation_thread", "thread_id": str(uuid.uuid4())}],
        paper_context={"kind": "library"},
        reasoning_level="deep",
        locale="zh-CN",
        time_zone="Asia/Shanghai",
        depth=2,
        branch_index=1,
    )
    conversation = Conversation(
        id=conversation_id,
        user_id=1,
        scope_type="global",
    )
    monkeypatch.setattr(
        conversation_repository,
        "require_owned",
        lambda *_args, **_kwargs: conversation,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat_data.conversation_policy.require_can_continue",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        turn_repository,
        "active_path",
        lambda *_args, **_kwargs: (conversation, [source]),
    )
    replace_context = MagicMock()
    monkeypatch.setattr(
        conversation_repository,
        "update_paper_context",
        replace_context,
    )
    branch = ConversationTurnBranchCreateRequest(
        turn_id=uuid.uuid4(),
        response_id=uuid.uuid4(),
        user_query="新的问题",
    )

    inherited = SqlAlchemyConversationChatData(MagicMock(spec=Session)).branch_request(
        actor=_current_user(),
        conversation_id=conversation_id,
        source_turn_id=source.id,
        request=branch,
    )

    assert inherited.turn_id == branch.turn_id
    assert inherited.response_id == branch.response_id
    assert inherited.user_query == branch.user_query
    assert [context.model_dump(mode="json") for context in inherited.contexts] == (
        source.contexts
    )
    assert inherited.reasoning_level.value == "deep"
    assert inherited.locale == "zh-CN"
    assert inherited.time_zone == "Asia/Shanghai"
    assert replace_context.call_args.kwargs["request"].kind == "library"


def test_conversation_list_cursor_is_bound_to_paper_scope() -> None:
    gateway = MagicMock()
    next_position = ConversationListPosition(
        pinned_at=None,
        updated_at=datetime.now(timezone.utc),
        conversation_id=uuid.uuid4(),
    )
    gateway.list_conversations.return_value = ConversationPage(
        items=[],
        next_position=next_position,
    )
    service = Conversations(
        gateway=gateway,
        list_cursors=SignedCursorCodec(
            "test-secret",
            revision="conversation-list-v2",
            error_code="conversation_cursor_expired",
        ),
        turn_cursors=MagicMock(),
        journal=MagicMock(spec=OperationJournal),
    )
    document_id = uuid.uuid4()
    first_page = service.list_page(
        actor=_current_user(),
        request=ConversationListRequest(
            scope_type=ConversationScopeType.PAPER,
            scope_id=document_id,
            limit=20,
        ),
    )
    assert first_page.next_cursor is not None
    assert gateway.list_conversations.call_args.kwargs["scope_id"] == document_id

    with pytest.raises(AppError) as exc_info:
        service.list_page(
            actor=_current_user(),
            request=ConversationListRequest(
                scope_type=ConversationScopeType.PAPER,
                scope_id=uuid.uuid4(),
                cursor=first_page.next_cursor,
                limit=20,
            ),
        )
    assert exc_info.value.code == "conversation_cursor_expired"


def test_owned_conversation_lookup_filters_id_and_user_in_one_query() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = None

    with pytest.raises(AppError):
        conversation_repository.require_owned(
            db,
            conversation_id=uuid.uuid4(),
            user_id=73,
        )

    statement = str(db.scalar.call_args.args[0])
    assert "conversations.id" in statement
    assert "conversations.user_id" in statement


def test_project_conversation_list_can_filter_current_document() -> None:
    document_id = uuid.uuid4()
    project_id = uuid.uuid4()
    request = ConversationListRequest(
        scope_type=ConversationScopeType.PROJECT,
        scope_id=project_id,
        context_document_id=document_id,
    )
    assert request.context_document_id == document_id

    db = MagicMock(spec=Session)
    result = MagicMock()
    result.all.return_value = []
    db.scalars.return_value = result
    conversation_repository.list(
        db,
        user_id=73,
        archived=False,
        scope_type=ConversationScopeType.PROJECT,
        scope_id=project_id,
        context_document_id=document_id,
        limit=20,
        position=None,
    )
    statement = str(db.scalars.call_args.args[0])
    assert "conversation_context_documents" in statement
    assert "conversations.project_id" in statement

    with pytest.raises(ValidationError):
        ConversationListRequest(
            scope_type=ConversationScopeType.PAPER,
            scope_id=document_id,
            context_document_id=document_id,
        )


def test_paper_conversation_scope_is_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Paper",
        user_id=1,
        scope_type="paper",
        document_id=uuid.uuid4(),
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository.conversation_policy.require_can_continue",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(AppError) as exc_info:
        conversation_repository.move(
            db,
            conversation_id=conversation.id,
            user_id=1,
            request=ConversationMoveRequest(scope_type="global"),
        )

    assert exc_info.value.code == "paper_conversation_scope_fixed"
    db.commit.assert_not_called()


def test_moving_project_conversation_to_library_resets_paper_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Project",
        user_id=1,
        scope_type="project",
        project_id=uuid.uuid4(),
        paper_context_kind="selection",
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository.conversation_policy.require_can_continue",
        lambda *_args, **_kwargs: None,
    )

    move_result = conversation_repository.move(
        db,
        conversation_id=conversation.id,
        user_id=1,
        request=ConversationMoveRequest(scope_type="global"),
    )
    moved = move_result.value

    assert move_result.changed is True
    assert moved.scope_type == "global"
    assert moved.project_id is None
    assert moved.paper_context_kind == "library"
    assert db.execute.call_count == 2
    db.commit.assert_not_called()


def test_archiving_a_conversation_also_unpins_it() -> None:
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Pinned",
        user_id=1,
        scope_type="global",
        pinned_at=now,
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation

    update_result = conversation_repository.update(
        db,
        conversation_id=conversation.id,
        user_id=1,
        request=ConversationUpdateRequest(archived=True),
    )
    updated = update_result.value

    assert update_result.changed is True
    assert updated.archived_at is not None
    assert updated.pinned_at is None
    db.commit.assert_not_called()
    db.flush.assert_called()


def test_conversation_scope_payloads_reject_inconsistent_ids() -> None:
    with pytest.raises(ValidationError):
        ConversationCreateRequest.model_validate({"scope_type": "project"})
    with pytest.raises(ValidationError):
        ConversationCreateRequest.model_validate(
            {
                "scope_type": "global",
                "scope_id": str(uuid.uuid4()),
            }
        )


def test_selected_paper_context_deduplicates_and_sorts_ids() -> None:
    first = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second = uuid.UUID("00000000-0000-0000-0000-000000000002")

    context = SelectedPaperContext.model_validate(
        {
            "project_ids": [str(second), str(first), str(second)],
            "document_ids": [str(second), str(first), str(first)],
        }
    )

    assert context.project_ids == [first, second]
    assert context.document_ids == [first, second]


def test_library_paper_context_rejects_selection_fields() -> None:
    with pytest.raises(ValidationError):
        LibraryPaperContext.model_validate(
            {"kind": "library", "document_ids": [str(uuid.uuid4())]}
        )


def test_conversation_context_keeps_anchor_and_drops_lost_extra_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor_project = uuid.uuid4()
    lost_project = uuid.uuid4()
    accessible_document = uuid.uuid4()
    lost_document = uuid.uuid4()
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Project chat",
        user_id=1,
        scope_type="project",
        project_id=anchor_project,
        paper_context_kind="selection",
    )
    db = MagicMock(spec=Session)
    project_rows = MagicMock()
    project_rows.all.return_value = [lost_project]
    document_rows = MagicMock()
    document_rows.all.return_value = [accessible_document, lost_document]
    db.scalars.side_effect = [project_rows, document_rows]
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository.get_project_access",
        lambda _db, *, project_id, user_id: (
            object() if project_id == anchor_project else None
        ),
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository.get_document_access",
        lambda _db, *, document_id, user_id: (
            object() if document_id == accessible_document else None
        ),
    )

    context = conversation_repository.paper_context(
        db,
        conversation=conversation,
        user_id=1,
    )

    assert context.kind == "selection"
    assert context.project_ids == [anchor_project]
    assert context.document_ids == [accessible_document]


def test_global_conversation_defaults_to_accessible_library_context() -> None:
    db = MagicMock(spec=Session)

    conversation = conversation_repository.create(
        db,
        request=ConversationCreateRequest(scope_type="global"),
        user_id=1,
        refresh_result=False,
    )

    assert conversation.paper_context_kind == "library"
    db.commit.assert_not_called()
    db.flush.assert_called()


def test_paper_context_snapshot_only_loads_anchor_full_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor_id = uuid.uuid4()
    extra_id = uuid.uuid4()
    papers = {
        anchor_id: MagicMock(
            id=anchor_id,
            title="Anchor",
            abstract="Anchor abstract",
            raw_content="Anchor full text",
            keywords=["anchor"],
            authors=["A"],
            publish_date=None,
        ),
        extra_id: MagicMock(
            id=extra_id,
            title="Extra",
            abstract="Must not be injected",
            raw_content="Must not be injected",
            keywords=["extra"],
            authors=["B"],
            publish_date=None,
        ),
    }
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat_data.document_repository.find_accessible",
        lambda _db, *, document_id, user: papers.get(document_id),
    )
    db = MagicMock(spec=Session)
    db.execute.return_value.all.return_value = []
    adapter = SqlAlchemyConversationChatData(db)

    snapshot = adapter.context(
        actor=_current_user(),
        scope=ConversationChatScope(
            scope_type=ConversationScopeType.PAPER,
            project_id=None,
            document_id=anchor_id,
            paper_context=SelectedPaperContext(
                document_ids=[anchor_id, extra_id],
            ),
            tool_permissions=frozenset(WorkspacePermission),
            title_is_default=False,
        ),
    )

    by_id = {paper.document_id: paper for paper in snapshot.papers}
    assert by_id[anchor_id].raw_content == "Anchor full text"
    assert by_id[anchor_id].abstract == "Anchor abstract"
    assert by_id[extra_id].raw_content is None
    assert by_id[extra_id].abstract is None


def test_missing_conversation_is_the_only_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversation_repository,
        "require_owned",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AppError(
                code="conversation_not_found",
                message="Conversation not found",
                kind=FailureKind.NOT_FOUND,
            )
        ),
    )

    with pytest.raises(AppError) as exc_info:
        SqlAlchemyConversationGateway(MagicMock(spec=Session)).get(
            conversation_id=uuid.uuid4(),
            user_id=_current_user().id,
        )

    assert exc_info.value.kind is FailureKind.NOT_FOUND
    assert exc_info.value.code == "conversation_not_found"


def test_conversation_turn_serialization_errors_are_not_reported_as_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid.uuid4()
    conversation = Conversation(
        id=conversation_id,
        title="Conversation",
        user_id=1,
        scope_type="global",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        conversation_repository,
        "require_owned",
        lambda *_args, **_kwargs: conversation,
    )
    gateway = SqlAlchemyConversationGateway(MagicMock(spec=Session))

    with pytest.raises(ValueError, match="invalid message payload"):
        monkeypatch.setattr(
            "app.bootstrap.adapters.conversation_lifecycle.serialize_turns",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("invalid message payload")
            ),
        )
        monkeypatch.setattr(
            turn_repository,
            "list_turns",
            lambda *_args, **_kwargs: (conversation, [MagicMock()]),
        )
        monkeypatch.setattr(
            turn_repository,
            "branch_groups",
            lambda *_args, **_kwargs: {None: []},
        )
        gateway.turns(
            conversation_id=conversation_id,
            offset=0,
            limit=10,
            user_id=_current_user().id,
        )
