"""Focused OperationContext and journal behavior for the Zotero vertical."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, call
from uuid import UUID, uuid4

import pytest

from app.bootstrap.workflows.zotero import ZoteroWorkflow
from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroImportRequest,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroCallback,
    Zotero,
    ZoteroAccessToken,
    ZoteroConnectionChange,
    ZoteroCredentials,
    ZoteroRequestToken,
    ZoteroSyncBatch,
    ZoteroSyncMutation,
)
from app.modules.jobs.application.contracts import JobResponse
from app.modules.jobs.application.jobs import EnqueuedJob, OperationTransition
from app.modules.operation_journal.application import OperationJournal
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OAuthCallbackOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
    SchedulerOrigin,
    SignedCursorCodec,
)
from app.modules.jobs.application.callbacks import (
    JobCallbacks,
    ScheduledZoteroJobs,
)
from app.shared.domain import AppError


def _actor(actor_id: int = 7) -> Actor:
    return Actor(
        id=actor_id,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _service(
    *,
    gateway: MagicMock,
    journal: MagicMock,
    idempotency: MagicMock | None = None,
    jobs: MagicMock | None = None,
) -> Zotero:
    return Zotero(
        gateway=gateway,
        capacity=MagicMock(),
        idempotency=idempotency or MagicMock(),
        jobs=jobs or MagicMock(),
        journal=journal,
    )


def _job(
    *,
    job_id: UUID | None = None,
    operation: str = "zotero_import",
    status: str = "pending",
    progress_code: str | None = None,
) -> JobResponse:
    return JobResponse(
        id=job_id or uuid4(),
        operation=operation,
        document_id=None,
        project_id=None,
        status=status,
        progress_code=progress_code,
        error_code=None,
        result=None,
        created_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
    )


def test_oauth_pending_persists_only_causality_and_is_not_journaled() -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    service = _service(gateway=gateway, journal=journal)
    operation = _operation()
    token = ZoteroRequestToken(token="request-token", secret="secret")

    response = service.save_oauth_request(
        actor=_actor(),
        operation=operation,
        request_token=token,
        auth_url="https://www.zotero.org/oauth/authorize",
        return_path="/library",
        intent="import",
    )

    assert response == ZoteroConnectResponse(
        auth_url="https://www.zotero.org/oauth/authorize"
    )
    assert gateway.save_oauth_request.call_args.kwargs == {
        "user_id": 7,
        "request_token": token,
        "return_path": "/library",
        "intent": "import",
        "correlation_id": operation.trace.correlation_id,
        "origin_operation_id": operation.trace.operation_id,
    }
    journal.append.assert_not_called()


def test_expired_oauth_callback_retains_safe_return_path_for_workflow() -> None:
    gateway = MagicMock()
    gateway.consume_oauth_callback.return_value = PreparedZoteroCallback(
        user_id=7,
        request_token=ZoteroRequestToken(token="expired", secret="secret"),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        return_path="/library",
        intent="import",
    )
    service = _service(
        gateway=gateway,
        journal=MagicMock(spec=OperationJournal),
    )

    prepared = service.consume_oauth_callback(
        oauth_token="expired",
        now=datetime.now(UTC),
    )

    assert prepared is not None
    assert prepared.return_path == "/library"
    assert gateway.method_calls == [
        call.consume_oauth_callback(oauth_token="expired"),
    ]


@pytest.mark.parametrize("method", ["complete", "fail"])
def test_background_terminal_transition_suppresses_concurrent_replay_journal(
    method: str,
) -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    idempotency = MagicMock()
    jobs = MagicMock()
    jobs.find_by_idempotency_key.return_value = None
    jobs.list.return_value = []
    operation_id = uuid4()
    claim_id = uuid4()
    jobs.get.return_value = _job(job_id=operation_id)
    transition = OperationTransition(job=_job(job_id=operation_id), changed=False)
    getattr(idempotency, method).return_value = transition
    service = _service(
        gateway=gateway,
        journal=journal,
        idempotency=idempotency,
        jobs=jobs,
    )

    if method == "complete":
        changed = service.complete_background_operation(
            actor=_actor(),
            operation=_operation(),
            operation_id=operation_id,
            claim_id=claim_id,
            result={"items": []},
        )
    else:
        changed = service.fail_background_operation(
            actor=_actor(),
            operation=_operation(),
            operation_id=operation_id,
            claim_id=claim_id,
            error_code="zotero_unavailable",
        )

    assert changed is False
    getattr(idempotency, method).assert_called_once()
    assert getattr(idempotency, method).call_args.kwargs["claim_id"] == claim_id
    journal.append.assert_not_called()


def test_import_enqueue_is_idempotent_and_never_serializes_credentials() -> None:
    revision = uuid4()
    gateway = MagicMock()
    gateway.credentials.return_value = ZoteroCredentials(
        user_id="42",
        api_key="never-in-job-payload",
        revision=revision,
    )
    jobs = MagicMock()
    jobs.find_by_idempotency_key.return_value = None
    jobs.list.return_value = []
    queued_job = _job()
    jobs.enqueue.return_value = EnqueuedJob(
        job=queued_job,
        created=True,
        payload={"item_keys": ["ITEM0001"], "credential_revision": str(revision)},
    )
    service = _service(
        gateway=gateway,
        journal=MagicMock(spec=OperationJournal),
        jobs=jobs,
    )

    result = service.enqueue_import(
        actor=_actor(),
        operation=_operation(),
        request=ZoteroImportRequest(item_keys=["ITEM0001"]),
        idempotency_key="request-1",
    )

    command = jobs.enqueue.call_args.kwargs["command"]
    assert result.id == queued_job.id
    assert command.task_name == "import_zotero_items"
    assert command.idempotency_key == "zotero-import:7:request-1"
    assert command.payload == {
        "item_keys": ["ITEM0001"],
        "credential_revision": str(revision),
    }
    assert "never-in-job-payload" not in repr(command)


def test_import_rejects_idempotency_key_reuse_for_different_items() -> None:
    revision = uuid4()
    gateway = MagicMock()
    gateway.credentials.return_value = ZoteroCredentials(
        user_id="42",
        api_key="secret",
        revision=revision,
    )
    jobs = MagicMock()
    jobs.enqueue.return_value = EnqueuedJob(
        job=_job(),
        created=False,
        payload={"item_keys": ["ITEM0001"], "credential_revision": str(revision)},
    )
    service = _service(
        gateway=gateway,
        journal=MagicMock(spec=OperationJournal),
        jobs=jobs,
    )

    with pytest.raises(AppError) as raised:
        service.enqueue_import(
            actor=_actor(),
            operation=_operation(),
            request=ZoteroImportRequest(item_keys=["ITEM0002"]),
            idempotency_key="request-1",
        )

    assert raised.value.code == "idempotency_key_reused"


def test_enqueue_rejects_second_active_zotero_operation_under_connection_lock() -> None:
    revision = uuid4()
    gateway = MagicMock()
    gateway.credentials.return_value = ZoteroCredentials(
        user_id="42",
        api_key="secret",
        revision=revision,
    )
    jobs = MagicMock()
    jobs.find_by_idempotency_key.return_value = None
    active = _job(operation="zotero_sync", status="running")
    jobs.list.return_value = [active]
    service = _service(
        gateway=gateway,
        journal=MagicMock(spec=OperationJournal),
        jobs=jobs,
    )

    with pytest.raises(AppError) as raised:
        service.enqueue_import(
            actor=_actor(),
            operation=_operation(),
            request=ZoteroImportRequest(item_keys=["ITEM0001"]),
            idempotency_key="request-2",
        )

    assert raised.value.code == "zotero_operation_active"
    assert raised.value.details == {
        "operation_id": str(active.id),
        "operation_kind": "sync",
    }
    gateway.credentials.assert_called_once_with(user_id=7, lock=True)
    jobs.enqueue.assert_not_called()


def test_active_operation_projects_safe_real_item_totals_and_stage() -> None:
    jobs = MagicMock()
    active = _job(status="running", progress_code="importing_papers")
    jobs.get.return_value = active
    jobs.payload.return_value = {
        "item_keys": ["ITEM0001", "ITEM0002"],
        "credential_revision": "must-not-be-exposed",
    }
    service = _service(
        gateway=MagicMock(),
        journal=MagicMock(spec=OperationJournal),
        jobs=jobs,
    )

    response = service.operation(
        actor=_actor(),
        operation_id=active.id,
        kind="import",
    )

    assert response.status == "running"
    assert response.progress_code == "importing_papers"
    assert response.counts.total == 2
    assert [item.status for item in response.items] == ["running", "running"]
    assert "credential_revision" not in response.model_dump()


def test_connection_change_journals_once_and_rejects_owner_mismatch() -> None:
    gateway = MagicMock()
    connection_id = uuid4()
    gateway.save_connection.return_value = ZoteroConnectionChange(
        connection_revision=connection_id,
        changed=True,
    )
    journal = MagicMock(spec=OperationJournal)
    service = _service(gateway=gateway, journal=journal)
    operation = _operation()
    callback = PreparedZoteroCallback(
        user_id=7,
        request_token=ZoteroRequestToken(token="token", secret="secret"),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id=operation.trace.correlation_id,
        origin_operation_id=operation.trace.operation_id,
        return_path="/library",
        intent="import",
    )
    access_token = ZoteroAccessToken(user_id="remote-user", api_key="api-key")

    assert service.complete_oauth_callback(
        actor=_actor(),
        operation=operation,
        callback=callback,
        access_token=access_token,
    )
    assert journal.append.call_args.kwargs["action"] == ("zotero.connection_connected")

    gateway.save_connection.return_value = ZoteroConnectionChange(
        connection_revision=connection_id,
        changed=False,
    )
    journal.reset_mock()
    assert service.complete_oauth_callback(
        actor=_actor(),
        operation=operation,
        callback=callback,
        access_token=access_token,
    )
    journal.append.assert_not_called()

    with pytest.raises(AppError) as raised:
        service.complete_oauth_callback(
            actor=_actor(8),
            operation=operation,
            callback=callback,
            access_token=access_token,
        )
    assert raised.value.code == "zotero_callback_owner_mismatch"


def test_disconnect_and_sync_suppress_noop_journal_entries() -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    service = _service(gateway=gateway, journal=journal)
    actor = _actor()
    operation = _operation()

    gateway.disconnect.return_value = None
    service.disconnect(actor=actor, operation=operation)
    journal.append.assert_not_called()

    gateway.disconnect.return_value = uuid4()
    service.disconnect(actor=actor, operation=operation)
    assert journal.append.call_args.kwargs["action"] == (
        "zotero.connection_disconnected"
    )

    journal.reset_mock()
    gateway.apply_sync.return_value = ZoteroSyncMutation(
        response=ZoteroSyncResponse(
            synced_papers_count=1,
            new_annotations_count=0,
        ),
        changed_document_ids=(),
    )
    service.complete_sync(
        actor=actor,
        operation=operation,
        batch=ZoteroSyncBatch(updates=(), failures=()),
        credential_revision=uuid4(),
    )
    journal.append.assert_not_called()

    changed_document_id = uuid4()
    gateway.apply_sync.return_value = ZoteroSyncMutation(
        response=ZoteroSyncResponse(
            synced_papers_count=1,
            new_annotations_count=2,
        ),
        changed_document_ids=(changed_document_id,),
    )
    service.complete_sync(
        actor=actor,
        operation=operation,
        batch=ZoteroSyncBatch(updates=(), failures=()),
        credential_revision=uuid4(),
    )
    assert journal.append.call_args.kwargs["action"] == "zotero.annotations_synced"
    assert journal.append.call_args.kwargs["resources"][0].id == str(
        changed_document_id
    )


class _Executor:
    def __init__(self, capabilities: object) -> None:
        self._capabilities = capabilities

    def query(self, operation):  # type: ignore[no-untyped-def]
        return operation(self._capabilities)

    def command(self, operation):  # type: ignore[no-untyped-def]
        return operation(self._capabilities)


def test_oauth_workflow_resumes_verified_owner_causality() -> None:
    actor = _actor()
    correlation_id = uuid4()
    origin_operation_id = uuid4()
    callback = PreparedZoteroCallback(
        user_id=actor.id,
        request_token=ZoteroRequestToken(token="token", secret="secret"),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id=correlation_id,
        origin_operation_id=origin_operation_id,
        return_path="/library",
        intent="import",
    )
    zotero = MagicMock()
    zotero.consume_oauth_callback.return_value = callback
    zotero.complete_oauth_callback.return_value = True
    identity = MagicMock()
    identity.resolve_actor_by_user_id.return_value = actor
    operations = MagicMock()
    operations.exchange_access_token.return_value = ZoteroAccessToken(
        user_id="remote-user",
        api_key="api-key",
    )
    operations.verify_access_token.return_value = True
    workflow = ZoteroWorkflow(
        executor=_Executor(  # type: ignore[arg-type]
            SimpleNamespace(zotero=zotero, identity=identity)
        ),
        operations=operations,
        operation_factory=OperationContextFactory(),
        cursors=SignedCursorCodec(
            "test-zotero-cursor-key",
            revision="zotero-test-v1",
            error_code="zotero_cursor_invalid",
        ),
    )
    request = RequestReference(uuid4())

    result = workflow.callback(
        oauth_token="token",
        oauth_verifier="verifier",
        request=request,
    )
    assert result.state == "connected"
    assert result.return_path == "/library"

    operation = zotero.complete_oauth_callback.call_args.kwargs["operation"]
    assert operation.trace.correlation_id == correlation_id
    assert operation.trace.causation_id == origin_operation_id
    assert operation.initiated_by is OperationInitiator.SYSTEM
    assert operation.credential is None
    assert operation.origin == OAuthCallbackOrigin(
        request=request,
        provider="zotero",
    )
    assert zotero.complete_oauth_callback.call_args.kwargs["actor"] is actor


def test_expired_oauth_workflow_returns_to_original_internal_page() -> None:
    callback = PreparedZoteroCallback(
        user_id=7,
        request_token=ZoteroRequestToken(token="expired", secret="secret"),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        return_path="/settings?section=connections",
        intent="manage",
    )
    zotero = MagicMock()
    zotero.consume_oauth_callback.return_value = callback
    operations = MagicMock()
    workflow = ZoteroWorkflow(
        executor=_Executor(  # type: ignore[arg-type]
            SimpleNamespace(zotero=zotero)
        ),
        operations=operations,
        operation_factory=OperationContextFactory(),
        cursors=SignedCursorCodec(
            "test-zotero-cursor-key",
            revision="zotero-test-v1",
            error_code="zotero_cursor_invalid",
        ),
    )

    result = workflow.callback(
        oauth_token="expired",
        oauth_verifier="unused",
        request=RequestReference(uuid4()),
    )

    assert result.return_path == "/settings?section=connections"
    assert result.intent == "manage"
    assert result.state == "zotero_oauth_expired"
    operations.exchange_access_token.assert_not_called()


def test_scheduler_journals_only_jobs_that_were_created() -> None:
    created_job_id = uuid4()
    schedules = MagicMock()
    schedules.schedule_zotero_sync.return_value = ScheduledZoteroJobs(
        total_users=2,
        scheduled_jobs=1,
        skipped_users=1,
        created_job_ids=(created_job_id,),
    )
    journal = MagicMock(spec=OperationJournal)
    callbacks = JobCallbacks(
        lifecycle=MagicMock(),
        handlers={},
        schedules=schedules,
        journal=journal,
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin(task_name="zotero_sync", run_id=uuid4()),
        credential=None,
    )

    response = callbacks.schedule_zotero_sync(
        operation=operation,
        threshold_seconds=3600,
    )

    assert response["scheduled_jobs"] == 1
    assert schedules.schedule_zotero_sync.call_args.kwargs == {
        "threshold_seconds": 3600,
        "correlation_id": operation.trace.correlation_id,
        "origin_operation_id": operation.trace.operation_id,
    }
    change = tuple(journal.append_many.call_args.kwargs["changes"])[0]
    assert change.action == "job.created"
    assert change.resources[0].id == str(created_job_id)
