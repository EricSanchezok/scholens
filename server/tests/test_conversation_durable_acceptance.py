from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.bootstrap.adapters.conversation_chat import (
    DefaultConversationChatGateway,
    _resolve_thread_command,
)
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.database.models import Conversation
from app.modules.conversations.application.chat import (
    ConversationChatScope,
    ConversationGenerationPreparation,
    ConversationTurnStart,
    PersistedChatResponse,
)
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationGenerationAccepted,
    LibraryPaperContext,
)
from app.modules.conversations.application.contracts.contexts import (
    AnnotationThreadTurnContext,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationTurnCreateRequest,
)
from app.modules.conversations.application.conversations import ConversationChange
from app.modules.conversations.domain import DEFAULT_CONVERSATION_TITLE
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.shared.domain.enums import ConversationScopeType, ReasoningLevel
from app.transport.http.public_v1.turns import _accepted_response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _turn_request() -> ConversationTurnCreateRequest:
    return ConversationTurnCreateRequest(
        turn_id=uuid4(),
        response_id=uuid4(),
        user_query="Explain this result",
        locale="en",
        time_zone="UTC",
    )


def _turn_start(request: ConversationTurnCreateRequest) -> ConversationTurnStart:
    operation_id = uuid4()
    correlation_id = uuid4()
    return ConversationTurnStart(
        turn_id=request.turn_id,
        response=PersistedChatResponse(
            id=request.response_id,
            turn_id=request.turn_id,
            variant_index=1,
            status="running",
            content="",
            references=None,
            trace=None,
            duration_ms=None,
        ),
        turn_operation_id=operation_id,
        correlation_id=correlation_id,
        turn_created=True,
        response_created=True,
        generation_kind="initial",
        suggestions=(),
    )


def _job_payload(
    *,
    conversation_id: object,
    request: ConversationTurnCreateRequest,
) -> dict[str, object]:
    return {
        "conversation_id": str(conversation_id),
        "turn_id": str(request.turn_id),
        "response_id": str(request.response_id),
        "generation_kind": "initial",
    }


def _accepted_job(
    *,
    request: ConversationTurnCreateRequest,
    scope_type: ConversationScopeType = ConversationScopeType.GLOBAL,
    scope_id: object | None = None,
    status: str = "pending",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=request.response_id,
        project_id=(scope_id if scope_type is ConversationScopeType.PROJECT else None),
        document_id=(scope_id if scope_type is ConversationScopeType.PAPER else None),
        status=status,
    )


def _executor_for(capabilities: SimpleNamespace) -> MagicMock:
    job_lookup = capabilities.job_commands.find_by_idempotency_key
    if isinstance(job_lookup.return_value, MagicMock):
        job_lookup.return_value = None
    executor = MagicMock()
    executor.query.side_effect = lambda query: query(capabilities)
    executor.command.side_effect = lambda command: command(capabilities)
    return executor


@pytest.mark.asyncio
async def test_start_acceptance_commits_all_durable_records_in_one_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    request = _turn_request()
    scope = ConversationChatScope(
        scope_type=ConversationScopeType.GLOBAL,
        project_id=None,
        document_id=None,
        paper_context=LibraryPaperCollection(),
        tool_permissions=frozenset({WorkspacePermission.READ}),
        title_is_default=True,
    )
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversation_chat_data.prepare.return_value = scope
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=True,
    )
    capabilities.conversation_chat_data.start_turn.return_value = _turn_start(request)
    executor = _executor_for(capabilities)
    wakeup = MagicMock()
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        dispatcher_wakeup=wakeup,
    )
    acquire = AsyncMock(return_value=True)
    metric = MagicMock()
    monkeypatch.setattr(gateway, "_acquire_acceptance_limits", acquire)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", metric
    )

    accepted = await gateway.accept_start(
        actor=_actor(),
        operation=MagicMock(),
        conversation_id=conversation_id,
        conversation=ConversationCreateRequest(scope_type=ConversationScopeType.GLOBAL),
        request=request,
        client_ip="127.0.0.1",
    )

    assert accepted.response_id == request.response_id
    executor.command.assert_called_once()
    executor.query.assert_not_called()
    acquire.assert_awaited_once()
    capabilities.conversations.create_with_id.assert_called_once()
    capabilities.conversation_chat_data.start_turn.assert_called_once()
    capabilities.job_commands.enqueue.assert_called_once()
    wakeup.notify.assert_called_once_with()
    assert [call.args[0] for call in metric.call_args_list] == [
        "scholens.conversation.accept.transaction_duration",
        "scholens.conversation.accept.total_duration",
    ]
    assert all(
        call.kwargs["attributes"] == {"status": "success", "generation_kind": "initial"}
        if call.args[0].endswith("transaction_duration")
        else call.kwargs["attributes"]
        == {"status": "accepted", "generation_kind": "initial"}
        for call in metric.call_args_list
    )


@pytest.mark.asyncio
async def test_slow_accept_transaction_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    request = _turn_request()
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=True,
    )
    capabilities.conversation_chat_data.prepare.return_value = ConversationChatScope(
        scope_type=ConversationScopeType.GLOBAL,
        project_id=None,
        document_id=None,
        paper_context=LibraryPaperCollection(),
        tool_permissions=frozenset(),
        title_is_default=True,
    )
    capabilities.conversation_chat_data.start_turn.return_value = _turn_start(request)
    transaction_started = threading.Event()
    transaction_release = threading.Event()
    executor = _executor_for(capabilities)

    def slow_command(command: Callable[[object], object]) -> object:
        transaction_started.set()
        transaction_release.wait(timeout=0.25)
        return command(capabilities)

    executor.command.side_effect = slow_command
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    acceptance = asyncio.create_task(
        gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=conversation_id,
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.GLOBAL
            ),
            request=request,
            client_ip="127.0.0.1",
        )
    )
    assert await asyncio.wait_for(
        asyncio.to_thread(transaction_started.wait),
        timeout=0.1,
    )
    assert not acceptance.done()

    loop_progressed = asyncio.Event()
    asyncio.get_running_loop().call_soon(loop_progressed.set)
    await asyncio.wait_for(loop_progressed.wait(), timeout=0.1)
    transaction_release.set()

    accepted = await acceptance
    assert accepted.response_id == request.response_id


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [True, False], ids=["commit", "rollback"])
async def test_cancelled_acceptance_resolves_the_transaction_before_compensation(
    monkeypatch: pytest.MonkeyPatch,
    commit: bool,
) -> None:
    conversation_id = uuid4()
    request = _turn_request()
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=True,
    )
    capabilities.conversation_chat_data.prepare.return_value = ConversationChatScope(
        scope_type=ConversationScopeType.GLOBAL,
        project_id=None,
        document_id=None,
        paper_context=LibraryPaperCollection(),
        tool_permissions=frozenset(),
        title_is_default=True,
    )
    capabilities.conversation_chat_data.start_turn.return_value = _turn_start(request)
    capabilities.job_commands.enqueue.return_value = SimpleNamespace(created=True)
    transaction_started = threading.Event()
    transaction_release = threading.Event()
    executor = _executor_for(capabilities)

    def slow_command(command: Callable[[object], object]) -> object:
        transaction_started.set()
        transaction_release.wait(timeout=0.25)
        if not commit:
            raise RuntimeError("transaction rolled back")
        return command(capabilities)

    executor.command.side_effect = slow_command
    wakeup = MagicMock()
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        dispatcher_wakeup=wakeup,
    )
    release_limit = AsyncMock()
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(gateway, "_release_acceptance_limit", release_limit)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    acceptance = asyncio.create_task(
        gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=conversation_id,
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.GLOBAL
            ),
            request=request,
            client_ip="127.0.0.1",
        )
    )
    assert await asyncio.wait_for(
        asyncio.to_thread(transaction_started.wait),
        timeout=0.1,
    )
    acceptance.cancel()
    await asyncio.sleep(0)
    assert not acceptance.done()
    transaction_release.set()

    with pytest.raises(asyncio.CancelledError):
        await acceptance

    if commit:
        wakeup.notify.assert_called_once_with()
        release_limit.assert_not_awaited()
    else:
        wakeup.notify.assert_not_called()
        release_limit.assert_awaited_once_with(
            actor=_actor(),
            response_id=request.response_id,
        )


@pytest.mark.asyncio
async def test_cancelled_limit_acquisition_preserves_a_possible_existing_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _turn_request()
    enforce = AsyncMock()
    acquire = AsyncMock(side_effect=asyncio.CancelledError())
    release = AsyncMock()
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.enforce_rate_limit",
        enforce,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.acquire_concurrency",
        acquire,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.release_concurrency",
        release,
    )

    with pytest.raises(asyncio.CancelledError):
        await DefaultConversationChatGateway._acquire_acceptance_limits(
            actor=_actor(),
            response_id=request.response_id,
            client_ip="127.0.0.1",
        )

    enforce.assert_awaited_once_with(
        user_id=_actor().id,
        ip_address="127.0.0.1",
        feature="chat",
        operation_id=str(request.response_id),
    )
    acquire.assert_awaited_once()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_thread_command_propagates_child_cancellation_without_spinning() -> None:
    def cancelled_command() -> object:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(
            _resolve_thread_command(cancelled_command),
            timeout=0.1,
        )


@pytest.mark.asyncio
async def test_start_conflict_releases_capacity_and_uses_stable_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _turn_request()
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.side_effect = AppError(
        code="conversation_turn_conflict",
        message="conflict",
        kind=FailureKind.CONFLICT,
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    release = AsyncMock()
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(gateway, "_release_acceptance_limit", release)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    with pytest.raises(AppError) as error:
        await gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=uuid4(),
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.GLOBAL
            ),
            request=request,
            client_ip="127.0.0.1",
        )

    assert error.value.code == "conversation_start_conflict"
    release.assert_awaited_once()
    capabilities.conversation_chat_data.start_turn.assert_not_called()
    capabilities.job_commands.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_ambiguous_acceptance_failure_preserves_an_exact_active_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    request = _turn_request()
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.side_effect = RuntimeError(
        "commit outcome is ambiguous"
    )
    capabilities.job_commands.find_by_idempotency_key.return_value = _accepted_job(
        request=request,
        status="running",
    )
    capabilities.conversation_chat_data.resume_generation.return_value = (
        ConversationGenerationPreparation(
            request=request,
            turn_start=_turn_start(request),
            paper_context=LibraryPaperCollection(),
        )
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    release = AsyncMock()
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(gateway, "_release_acceptance_limit", release)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    with pytest.raises(RuntimeError, match="commit outcome is ambiguous"):
        await gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=conversation_id,
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.GLOBAL
            ),
            request=request,
            client_ip="127.0.0.1",
        )

    release.assert_not_awaited()
    capabilities.conversation_chat_data.resume_generation.assert_called_once()


@pytest.mark.asyncio
async def test_start_rejects_existing_conversation_without_exact_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _turn_request()
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=False,
    )
    capabilities.conversation_chat_data.resume_generation.side_effect = AppError(
        code="conversation_response_not_found",
        message="not found",
        kind=FailureKind.NOT_FOUND,
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    release = AsyncMock()
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(gateway, "_release_acceptance_limit", release)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    with pytest.raises(AppError) as error:
        await gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=uuid4(),
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.GLOBAL
            ),
            request=request,
            client_ip="127.0.0.1",
        )

    assert error.value.code == "conversation_start_conflict"
    release.assert_awaited_once()
    capabilities.conversation_chat_data.prepare.assert_not_called()
    capabilities.conversation_chat_data.start_turn.assert_not_called()
    capabilities.job_commands.enqueue.assert_not_called()


def test_client_identified_conversation_identity_excludes_mutable_presentation() -> (
    None
):
    conversation_id = uuid4()
    existing = Conversation(
        id=conversation_id,
        user_id=7,
        title="A later generated title",
        scope_type=ConversationScopeType.PROJECT.value,
        project_id=uuid4(),
        paper_context_kind="selection",
        tool_permissions=["read"],
    )
    db = MagicMock(spec=Session)
    db.get.return_value = existing

    result = conversation_repository.create_with_id(
        db,
        conversation_id=conversation_id,
        request=ConversationCreateRequest(scope_type=ConversationScopeType.GLOBAL),
        user_id=7,
    )

    assert result.value is existing
    assert result.changed is False
    db.add.assert_not_called()


def test_client_identified_conversation_rejects_a_different_owner() -> None:
    conversation_id = uuid4()
    existing = Conversation(
        id=conversation_id,
        user_id=8,
        title=DEFAULT_CONVERSATION_TITLE,
        scope_type=ConversationScopeType.GLOBAL.value,
        paper_context_kind="library",
        tool_permissions=["read", "write"],
    )
    db = MagicMock(spec=Session)
    db.get.return_value = existing

    with pytest.raises(AppError) as error:
        conversation_repository.create_with_id(
            db,
            conversation_id=conversation_id,
            request=ConversationCreateRequest(scope_type=ConversationScopeType.GLOBAL),
            user_id=7,
        )

    assert error.value.code == "conversation_start_conflict"
    assert error.value.kind is FailureKind.CONFLICT


@pytest.mark.asyncio
async def test_start_replay_uses_immutable_turn_snapshot_and_legacy_job_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    request = _turn_request()
    persisted = _turn_start(request)
    persisted = ConversationTurnStart(
        turn_id=persisted.turn_id,
        response=persisted.response,
        turn_operation_id=persisted.turn_operation_id,
        correlation_id=persisted.correlation_id,
        turn_created=False,
        response_created=False,
        generation_kind="initial",
        suggestions=(),
    )
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversation_chat_data.resume_generation.return_value = (
        ConversationGenerationPreparation(
            request=request,
            turn_start=persisted,
            paper_context=LibraryPaperCollection(),
        )
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=False,
    )
    legacy_job = _accepted_job(request=request)
    legacy_job.payload = _job_payload(
        conversation_id=conversation_id,
        request=request,
    )
    capabilities.job_commands.find_by_idempotency_key.return_value = legacy_job
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    limits = AsyncMock(
        side_effect=AppError(
            code="rate_limit_exceeded",
            message="limit",
            kind=FailureKind.RATE_LIMITED,
        )
    )
    monkeypatch.setattr(gateway, "_acquire_acceptance_limits", limits)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    accepted = await gateway.accept_start(
        actor=_actor(),
        operation=MagicMock(),
        conversation_id=conversation_id,
        conversation=ConversationCreateRequest(
            scope_type=ConversationScopeType.GLOBAL,
            title="Original title no longer stored on the Conversation",
        ),
        request=request,
        client_ip="127.0.0.1",
    )

    assert accepted.response_id == request.response_id
    assert set(legacy_job.payload) == {
        "conversation_id",
        "turn_id",
        "response_id",
        "generation_kind",
    }
    capabilities.conversation_chat_data.prepare.assert_not_called()
    capabilities.conversation_chat_data.start_turn.assert_not_called()
    capabilities.job_commands.enqueue.assert_not_called()
    limits.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_replay_fallback_rejects_a_different_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    original = _turn_request()
    changed = original.model_copy(update={"user_query": "Different question"})
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.job_commands.find_by_idempotency_key.return_value = _accepted_job(
        request=original,
        status="running",
    )
    capabilities.conversation_chat_data.resume_generation.return_value = (
        ConversationGenerationPreparation(
            request=original,
            turn_start=_turn_start(original),
            paper_context=LibraryPaperCollection(),
        )
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    limits = AsyncMock(
        side_effect=AppError(
            code="rate_limit_exceeded",
            message="limit",
            kind=FailureKind.RATE_LIMITED,
        )
    )
    monkeypatch.setattr(gateway, "_acquire_acceptance_limits", limits)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    with pytest.raises(AppError) as error:
        await gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=conversation_id,
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.GLOBAL
            ),
            request=changed,
            client_ip="127.0.0.1",
        )

    assert error.value.code == "rate_limit_exceeded"
    executor.command.assert_not_called()
    capabilities.conversations.create_with_id.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update",
    [
        {"user_query": "Different question"},
        {"contexts": [AnnotationThreadTurnContext(thread_id=uuid4())]},
        {"reasoning_level": ReasoningLevel.DEEP},
    ],
    ids=["query", "contexts", "reasoning"],
)
async def test_start_replay_rejects_changed_immutable_turn_content(
    monkeypatch: pytest.MonkeyPatch,
    update: dict[str, object],
) -> None:
    original = _turn_request()
    changed = original.model_copy(update=update)
    conversation_id = uuid4()
    persisted = _turn_start(original)
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversation_chat_data.resume_generation.return_value = (
        ConversationGenerationPreparation(
            request=original,
            turn_start=persisted,
            paper_context=LibraryPaperCollection(),
        )
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=False,
    )
    capabilities.job_commands.find_by_idempotency_key.return_value = _accepted_job(
        request=original
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    release = AsyncMock()
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(gateway, "_release_acceptance_limit", release)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    with pytest.raises(AppError) as error:
        await gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=conversation_id,
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.GLOBAL
            ),
            request=changed,
            client_ip="127.0.0.1",
        )

    assert error.value.code == "conversation_start_conflict"
    release.assert_not_awaited()
    capabilities.conversation_chat_data.start_turn.assert_not_called()
    capabilities.job_commands.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_start_replay_canonicalizes_postgres_null_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    original = _turn_request()
    request = ConversationTurnCreateRequest(
        turn_id=original.turn_id,
        response_id=original.response_id,
        user_query="Explain\x00 this",
        locale=original.locale,
        time_zone=original.time_zone,
    )
    assert request.user_query == "Explain this"
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=False,
    )
    capabilities.conversation_chat_data.resume_generation.return_value = (
        ConversationGenerationPreparation(
            request=request,
            turn_start=_turn_start(request),
            paper_context=LibraryPaperCollection(),
        )
    )
    capabilities.job_commands.find_by_idempotency_key.return_value = _accepted_job(
        request=request
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    accepted = await gateway.accept_start(
        actor=_actor(),
        operation=MagicMock(),
        conversation_id=conversation_id,
        conversation=ConversationCreateRequest(scope_type=ConversationScopeType.GLOBAL),
        request=request,
        client_ip="127.0.0.1",
    )

    assert accepted.response_id == request.response_id
    capabilities.conversation_chat_data.start_turn.assert_not_called()
    capabilities.job_commands.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_start_replay_validates_the_original_scope_after_a_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    request = _turn_request()
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=False,
    )
    capabilities.conversation_chat_data.resume_generation.return_value = (
        ConversationGenerationPreparation(
            request=request,
            turn_start=_turn_start(request),
            paper_context=LibraryPaperCollection(),
        )
    )
    capabilities.job_commands.find_by_idempotency_key.return_value = _accepted_job(
        request=request
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    accepted = await gateway.accept_start(
        actor=_actor(),
        operation=MagicMock(),
        conversation_id=conversation_id,
        conversation=ConversationCreateRequest(scope_type=ConversationScopeType.GLOBAL),
        request=request,
        client_ip="127.0.0.1",
    )

    assert accepted.response_id == request.response_id
    capabilities.conversation_chat_data.prepare.assert_not_called()
    capabilities.conversation_chat_data.start_turn.assert_not_called()


@pytest.mark.asyncio
async def test_start_replay_rejects_a_different_original_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    project_id = uuid4()
    request = _turn_request()
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=False,
    )
    capabilities.conversation_chat_data.resume_generation.return_value = (
        ConversationGenerationPreparation(
            request=request,
            turn_start=_turn_start(request),
            paper_context=LibraryPaperCollection(),
        )
    )
    capabilities.job_commands.find_by_idempotency_key.return_value = _accepted_job(
        request=request
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    release = AsyncMock()
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(gateway, "_release_acceptance_limit", release)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    with pytest.raises(AppError) as error:
        await gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=conversation_id,
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.PROJECT,
                scope_id=project_id,
                paper_context=LibraryPaperContext(),
            ),
            request=request,
            client_ip="127.0.0.1",
        )

    assert error.value.code == "conversation_start_conflict"
    release.assert_not_awaited()
    capabilities.conversation_chat_data.start_turn.assert_not_called()
    capabilities.job_commands.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_start_rolls_back_a_recreated_generation_when_its_job_is_a_tombstone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    request = _turn_request()
    capabilities = SimpleNamespace(
        conversations=MagicMock(),
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversations.create_with_id.return_value = ConversationChange(
        value=MagicMock(),
        changed=True,
    )
    capabilities.conversation_chat_data.prepare.return_value = ConversationChatScope(
        scope_type=ConversationScopeType.GLOBAL,
        project_id=None,
        document_id=None,
        paper_context=LibraryPaperCollection(),
        tool_permissions=frozenset(),
        title_is_default=True,
    )
    capabilities.conversation_chat_data.start_turn.return_value = _turn_start(request)
    capabilities.job_commands.enqueue.return_value = SimpleNamespace(
        created=False,
        payload=_job_payload(conversation_id=conversation_id, request=request),
        job=SimpleNamespace(id=request.response_id, status="completed"),
    )
    capabilities.job_commands.find_by_idempotency_key.return_value = _accepted_job(
        request=request,
        status="completed",
    )
    executor = _executor_for(capabilities)
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    release = AsyncMock()
    monkeypatch.setattr(
        gateway,
        "_acquire_acceptance_limits",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(gateway, "_release_acceptance_limit", release)
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.record_histogram", MagicMock()
    )

    with pytest.raises(AppError) as error:
        await gateway.accept_start(
            actor=_actor(),
            operation=MagicMock(),
            conversation_id=conversation_id,
            conversation=ConversationCreateRequest(
                scope_type=ConversationScopeType.GLOBAL
            ),
            request=request,
            client_ip="127.0.0.1",
        )

    assert error.value.code == "conversation_start_conflict"
    release.assert_awaited_once()
    capabilities.conversation_chat_data.start_turn.assert_called_once()
    capabilities.job_commands.enqueue.assert_called_once()


class _SubscriptionChat:
    def __init__(self) -> None:
        self.subscribe_calls = 0
        self.cancel = MagicMock()

    async def subscribe(self, **_kwargs: object) -> AsyncIterator[str]:
        self.subscribe_calls += 1

        async def events() -> AsyncIterator[str]:
            yield "event: start\ndata: {}\n\n"

        return events()


@pytest.mark.asyncio
async def test_direct_response_flushes_acceptance_before_durable_subscription() -> None:
    accepted = ConversationGenerationAccepted(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        response_id=uuid4(),
        variant_index=1,
        generation_kind="initial",
    )
    chat = _SubscriptionChat()

    response = await _accepted_response(
        accepted=accepted,
        chat=chat,  # type: ignore[arg-type]
        actor=_actor(),
        prefer=None,
        include_candidates=True,
    )

    assert isinstance(response, StreamingResponse)
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert chat.subscribe_calls == 0
    assert await anext(response.body_iterator) == ": accepted\n\n"
    assert chat.subscribe_calls == 0
    assert await anext(response.body_iterator) == "event: start\ndata: {}\n\n"
    assert chat.subscribe_calls == 1
    assert [item async for item in response.body_iterator] == []
    chat.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_respond_async_compatibility_returns_202_without_subscribing() -> None:
    accepted = ConversationGenerationAccepted(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        response_id=uuid4(),
        variant_index=1,
        generation_kind="initial",
    )
    chat = _SubscriptionChat()

    response = await _accepted_response(
        accepted=accepted,
        chat=chat,  # type: ignore[arg-type]
        actor=_actor(),
        prefer="respond-async",
        include_candidates=True,
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 202
    assert response.headers["preference-applied"] == "respond-async"
    assert chat.subscribe_calls == 0


@pytest.mark.asyncio
async def test_cancel_immediately_appends_a_durable_terminal_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    turn_id = uuid4()
    response_id = uuid4()
    capabilities = SimpleNamespace(
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversation_chat_data.cancel_generation.return_value = (
        PersistedChatResponse(
            id=response_id,
            turn_id=turn_id,
            variant_index=1,
            status="cancelled",
            content="",
            references=None,
            trace=None,
            duration_ms=10,
        )
    )
    executor = _executor_for(capabilities)
    store = SimpleNamespace(append_terminal=AsyncMock())
    release = AsyncMock()
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.ConversationEventStore",
        lambda _url: store,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.release_concurrency",
        release,
    )
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        event_store_url="redis://cache.invalid",
    )

    result = await gateway.cancel(
        actor=_actor(),
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response_id,
    )

    assert result.status == "cancelled"
    store.append_terminal.assert_awaited_once()
    terminal = store.append_terminal.call_args.kwargs
    assert terminal["response_id"] == response_id
    assert terminal["frame"].startswith("event: cancelled\n")
    assert f'"turn_id":"{turn_id}"' in terminal["frame"]
    capabilities.job_commands.cancel.assert_called_once()
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_cancel_waits_for_commit_and_runs_terminal_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    turn_id = uuid4()
    response_id = uuid4()
    capabilities = SimpleNamespace(
        conversation_chat_data=MagicMock(),
        job_commands=MagicMock(),
    )
    capabilities.conversation_chat_data.cancel_generation.return_value = (
        PersistedChatResponse(
            id=response_id,
            turn_id=turn_id,
            variant_index=1,
            status="cancelled",
            content="",
            references=None,
            trace=None,
            duration_ms=10,
        )
    )
    transaction_started = threading.Event()
    transaction_release = threading.Event()
    executor = _executor_for(capabilities)

    def slow_command(command: Callable[[object], object]) -> object:
        transaction_started.set()
        transaction_release.wait(timeout=0.25)
        return command(capabilities)

    executor.command.side_effect = slow_command
    store = SimpleNamespace(append_terminal=AsyncMock())
    release = AsyncMock()
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.ConversationEventStore",
        lambda _url: store,
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat.release_concurrency",
        release,
    )
    gateway = DefaultConversationChatGateway(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        event_store_url="redis://cache.invalid",
    )

    cancellation = asyncio.create_task(
        gateway.cancel(
            actor=_actor(),
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
        )
    )
    assert await asyncio.wait_for(
        asyncio.to_thread(transaction_started.wait),
        timeout=0.1,
    )
    cancellation.cancel()
    await asyncio.sleep(0)
    assert not cancellation.done()
    transaction_release.set()

    with pytest.raises(asyncio.CancelledError):
        await cancellation

    store.append_terminal.assert_awaited_once()
    capabilities.job_commands.cancel.assert_called_once()
    release.assert_awaited_once()
