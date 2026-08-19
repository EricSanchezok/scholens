from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.bootstrap.adapters.document_reflow_callbacks import (
    complete_document_reflow,
)
from app.bootstrap.adapters.document_reflow import SqlDocumentReflowGateway
from app.modules.jobs.application.contracts import (
    DocumentReflowAssetPayload,
    DocumentReflowWebhookData,
    JobResponse,
)
from app.modules.jobs.application.jobs import EnqueuedJob
from app.modules.reflows.infrastructure.models import (
    DocumentReflow,
    DocumentReflowAsset,
)
from app.modules.reflows.application.contracts import (
    DocumentReflowAssetUrlResponse,
    DocumentReflowResponse,
)
from app.modules.reflows.application.reflows import DocumentReflows
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import (
    DocumentProcessingStatus,
    JobOperation,
    JobStatus,
)


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _reflow_response(
    document_id,
    *,
    status: str,
    attempts: int = 0,
) -> DocumentReflowResponse:
    return DocumentReflowResponse(
        document_id=document_id,
        status=status,
        job_id=uuid4() if attempts else None,
        attempt_count=attempts,
        failure=None,
        pipeline_revision=None,
        parser_revision=None,
        warnings=[],
        blocks=[],
        assets=[],
        updated_at=datetime.now(UTC) if status != "not_requested" else None,
    )


def test_reflow_attempt_requires_mineru_before_enqueueing() -> None:
    document_id = uuid4()
    gateway = MagicMock()
    gateway.get.return_value = _reflow_response(
        document_id,
        status="not_requested",
    )
    require_mineru = MagicMock(
        side_effect=AppError(
            code="mineru_credential_required",
            message="Connect MinerU",
            kind=FailureKind.UNPROCESSABLE,
            retryable=True,
        )
    )
    reflows = DocumentReflows(
        access=MagicMock(return_value=SimpleNamespace(title="Paper")),
        gateway=gateway,
        require_mineru=require_mineru,
        journal=MagicMock(),
    )

    with pytest.raises(AppError) as raised:
        reflows.request_attempt(
            actor=_actor(),
            operation=MagicMock(spec=OperationContext),
            document_id=document_id,
            idempotency_key="reader-intent-1",
        )

    assert raised.value.code == "mineru_credential_required"
    gateway.ensure.assert_not_called()


@pytest.mark.parametrize("status", ["pending", "processing", "completed"])
def test_reflow_attempt_returns_active_or_completed_work_without_new_token(
    status: str,
) -> None:
    document_id = uuid4()
    current = _reflow_response(document_id, status=status, attempts=1)
    gateway = MagicMock()
    gateway.get.return_value = current
    require_mineru = MagicMock()
    reflows = DocumentReflows(
        access=MagicMock(return_value=SimpleNamespace(title="Paper")),
        gateway=gateway,
        require_mineru=require_mineru,
        journal=MagicMock(),
    )

    result = reflows.request_attempt(
        actor=_actor(),
        operation=MagicMock(spec=OperationContext),
        document_id=document_id,
        idempotency_key="reader-intent-1",
    )

    assert result is current
    require_mineru.assert_not_called()
    gateway.ensure.assert_not_called()


def test_failed_reflow_starts_one_revision_bound_idempotent_attempt() -> None:
    document_id = uuid4()
    current = _reflow_response(document_id, status="failed", attempts=1)
    scheduled = _reflow_response(document_id, status="pending", attempts=2)
    gateway = MagicMock()
    gateway.get.return_value = current
    gateway.ensure.return_value = (scheduled, True)
    journal = MagicMock()
    operation = MagicMock(spec=OperationContext)
    actor = _actor()
    reflows = DocumentReflows(
        access=MagicMock(return_value=SimpleNamespace(title="Paper")),
        gateway=gateway,
        require_mineru=MagicMock(),
        journal=journal,
    )

    result = reflows.request_attempt(
        actor=actor,
        operation=operation,
        document_id=document_id,
        idempotency_key="reader-intent-2",
    )

    assert result is scheduled
    gateway.ensure.assert_called_once_with(
        actor=actor,
        operation=operation,
        document_id=document_id,
        idempotency_key="reader-intent-2",
    )
    journal.append.assert_called_once()


class _ConcurrentReflowState:
    def __init__(self, document_id) -> None:
        self.source_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.document = SimpleNamespace(
            id=document_id,
            title="Concurrent paper",
            original_filename="concurrent.pdf",
            s3_object_key=f"documents/{document_id}/source.pdf",
            parser_archive_s3_key=None,
            parser_backend="pymupdf4llm",
            parser_version="local-v1",
            processing_status=DocumentProcessingStatus.COMPLETED.value,
        )
        self.artifact: DocumentReflow | None = None
        self.jobs: dict[object, JobResponse] = {}
        self.jobs_by_key: dict[str, JobResponse] = {}
        self.outbox: list[object] = []
        self.journal_entries = 0


class _ConcurrentSession:
    def __init__(self, state: _ConcurrentReflowState) -> None:
        self.state = state
        self.owns_source_lock = False

    def add(self, artifact: DocumentReflow) -> None:
        self.state.artifact = artifact

    def flush(self) -> None:
        artifact = self.state.artifact
        if artifact is None:
            return
        now = datetime.now(UTC)
        artifact.status = artifact.status or "pending"
        artifact.updated_at = now
        artifact.created_at = now
        artifact.__dict__["blocks"] = []
        artifact.__dict__["assets"] = []
        artifact.__dict__["job"] = self.state.jobs[artifact.job_id]

    def release(self) -> None:
        if self.owns_source_lock:
            self.owns_source_lock = False
            self.state.source_lock.release()


class _ConcurrentJobs:
    def __init__(self, state: _ConcurrentReflowState) -> None:
        self.state = state

    def find_by_idempotency_key(self, *, key: str) -> JobResponse | None:
        return self.state.jobs_by_key.get(key)

    def enqueue(self, *, command) -> EnqueuedJob:
        now = datetime.now(UTC)
        job = JobResponse(
            id=command.job_id,
            operation=command.operation.value,
            document_id=command.document_id,
            project_id=None,
            status=JobStatus.PENDING.value,
            progress_code=None,
            error_code=None,
            result=None,
            created_at=now,
            started_at=None,
            completed_at=None,
        )
        self.state.jobs[job.id] = job
        self.state.jobs_by_key[command.idempotency_key] = job
        self.state.outbox.append(command.job_id)
        return EnqueuedJob(job=job, created=True)


class _ConcurrentGateway(SqlDocumentReflowGateway):
    def __init__(
        self,
        db: _ConcurrentSession,
        state: _ConcurrentReflowState,
        initial_read_barrier: threading.Barrier,
    ) -> None:
        self._db = db  # type: ignore[assignment]
        self._jobs = _ConcurrentJobs(state)  # type: ignore[assignment]
        self._state = state
        self._initial_read_barrier = initial_read_barrier

    def _lock_source(self, document_id):  # type: ignore[no-untyped-def]
        assert document_id == self._state.document.id
        self._state.source_lock.acquire()
        self._db.owns_source_lock = True
        return self._state.document

    def _load(self, document_id, *, lock=False):  # type: ignore[no-untyped-def]
        assert document_id == self._state.document.id
        artifact = self._state.artifact
        if artifact is not None:
            artifact.__dict__["job"] = self._state.jobs[artifact.job_id]
            artifact.__dict__["blocks"] = []
            artifact.__dict__["assets"] = []
        return artifact

    def get(self, *, document_id):  # type: ignore[no-untyped-def]
        result = super().get(document_id=document_id)
        if result.status == "not_requested":
            self._initial_read_barrier.wait(timeout=5)
        return result


class _ConcurrentJournal:
    def __init__(self, state: _ConcurrentReflowState) -> None:
        self._state = state

    def append(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        with self._state.state_lock:
            self._state.journal_entries += 1


@pytest.mark.parametrize("keys", [("same", "same"), ("left", "right")])
def test_first_reflow_attempt_serializes_on_the_document_row(keys) -> None:
    document_id = uuid4()
    state = _ConcurrentReflowState(document_id)
    barrier = threading.Barrier(2)
    journal = _ConcurrentJournal(state)

    def request(idempotency_key: str) -> DocumentReflowResponse:
        session = _ConcurrentSession(state)
        gateway = _ConcurrentGateway(session, state, barrier)
        reflows = DocumentReflows(
            access=MagicMock(return_value=SimpleNamespace(title="Paper")),
            gateway=gateway,
            require_mineru=MagicMock(),
            journal=journal,  # type: ignore[arg-type]
        )
        operation = MagicMock(spec=OperationContext)
        operation.trace.correlation_id = uuid4()
        operation.trace.operation_id = uuid4()
        try:
            return reflows.request_attempt(
                actor=_actor(),
                operation=operation,
                document_id=document_id,
                idempotency_key=idempotency_key,
            )
        finally:
            # Releasing here models the request transaction commit that releases
            # PostgreSQL's Document FOR UPDATE lock.
            session.release()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(request, keys))

    assert [result.status for result in results] == ["pending", "pending"]
    assert results[0].job_id == results[1].job_id
    assert len(state.jobs) == 1
    assert len(state.outbox) == 1
    assert state.artifact is not None
    assert state.artifact.attempt_count == 1
    assert state.journal_entries == 1


def test_reflow_source_lock_uses_the_stable_document_row() -> None:
    db = MagicMock()
    document = SimpleNamespace(id=uuid4())
    db.scalar.return_value = document
    gateway = SqlDocumentReflowGateway(db)

    assert gateway._lock_source(document.id) is document

    statement = db.scalar.call_args.args[0]
    sql = str(statement)
    assert "documents.id" in sql
    assert "FOR UPDATE" in sql


def test_not_requested_reflow_has_no_synthetic_updated_at() -> None:
    document_id = uuid4()
    gateway = SqlDocumentReflowGateway(MagicMock())
    gateway._load = MagicMock(return_value=None)  # type: ignore[method-assign]

    response = gateway.get(document_id=document_id)

    assert response.status == "not_requested"
    assert response.updated_at is None


def _scope(markdown: str = "# Paper\n\nSource paragraph."):
    document_id = uuid4()
    job_id = uuid4()
    job = SimpleNamespace(
        id=job_id,
        operation=JobOperation.DOCUMENT_REFLOW.value,
        requested_by_id=7,
        document_id=document_id,
        status=JobStatus.RUNNING.value,
        origin_operation_id=uuid4(),
        correlation_id=uuid4(),
    )
    artifact = DocumentReflow(
        document_id=document_id,
        job_id=job_id,
        status="pending",
        attempt_count=1,
    )
    artifact.blocks = []
    artifact.assets = []
    document = SimpleNamespace(
        id=document_id,
        raw_content=markdown,
        sha256=hashlib.sha256(b"canonical-pdf").hexdigest(),
    )
    db = MagicMock()
    db.get.side_effect = lambda model, key: (
        artifact if model is DocumentReflow and key == document_id else document
    )
    return db, job, artifact, document


def _completed_callback(job_id, document_id, markdown: str):
    return DocumentReflowWebhookData.model_validate(
        {
            "task_id": str(job_id),
            "status": "completed",
            "result": {
                "document_id": str(document_id),
                "source_hash": hashlib.sha256(b"canonical-pdf").hexdigest(),
                "pipeline_revision": "mineru-continuous-ast-v1",
                "parser_revision": "mineru-cloud-v1",
                "blocks": [
                    {
                        "id": "title-block",
                        "index": 0,
                        "kind": "title",
                        "render_markdown": "# Paper",
                        "heading_level": 1,
                        "source_spans": [
                            {
                                "page_number": 1,
                                "source_rect": {
                                    "x": 0.1,
                                    "y": 0.1,
                                    "width": 0.5,
                                    "height": 0.05,
                                },
                                "source_text": "Paper",
                            }
                        ],
                        "presentation_status": "verbatim",
                    },
                    {
                        "id": "body-block",
                        "index": 1,
                        "kind": "paragraph",
                        "render_markdown": "Source paragraph.",
                        "source_spans": [
                            {
                                "page_number": 1,
                                "source_rect": {
                                    "x": 0.1,
                                    "y": 0.2,
                                    "width": 0.8,
                                    "height": 0.1,
                                },
                                "source_text": "Source paragraph.",
                            }
                        ],
                        "presentation_status": "verbatim",
                    },
                ],
                "assets": [],
            },
            "usage_events": [],
        }
    )


def test_reflow_completion_persists_sequential_evidence_bound_blocks() -> None:
    markdown = "# Paper\n\nSource paragraph."
    db, job, artifact, document = _scope(markdown)
    callback = _completed_callback(job.id, document.id, markdown)

    with (
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.complete",
            return_value=(job, True),
        ) as complete,
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.schedule_storage_deletion",
            return_value=None,
        ),
    ):
        result = complete_document_reflow(
            db,
            actor=_actor(),
            job_id=job.id,
            callback=callback,
        )

    assert result.value == {"accepted": True}
    assert [block.render_markdown for block in artifact.blocks] == [
        "# Paper",
        "Source paragraph.",
    ]
    assert artifact.blocks[0].source_spans[0]["source_text"] == "Paper"
    assert artifact.pipeline_revision == "mineru-continuous-ast-v1"
    assert artifact.parser_revision == "mineru-cloud-v1"
    assert artifact.status == "completed"
    assert artifact.completed_at is not None
    complete.assert_called_once()


def test_reflow_completion_replaces_assets_and_schedules_obsolete_objects() -> None:
    markdown = "# Paper\n\nSource paragraph."
    db, job, artifact, document = _scope(markdown)
    artifact.assets = [
        DocumentReflowAsset(
            id="old-asset",
            document_id=document.id,
            object_key="documents/document-id/reflow/assets/old.png",
            kind="raster",
            content_type="image/png",
            width=100,
            height=100,
            page_number=1,
            source_rect={"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            checksum="b" * 64,
        )
    ]
    callback = _completed_callback(job.id, document.id, markdown)
    assert callback.result is not None
    callback.result.assets = [
        DocumentReflowAssetPayload.model_validate(
            {
                "id": "figure-1",
                "object_key": "documents/document-id/reflow/assets/figure-1.png",
                "kind": "vector",
                "content_type": "image/png",
                "width": 640,
                "height": 480,
                "page_number": 1,
                "source_rect": {
                    "x": 0.1,
                    "y": 0.4,
                    "width": 0.7,
                    "height": 0.3,
                },
                "checksum": "a" * 64,
            }
        )
    ]

    with (
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.complete",
            return_value=(job, True),
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.schedule_storage_deletion"
        ) as schedule_deletion,
    ):
        result = complete_document_reflow(
            db,
            actor=_actor(),
            job_id=job.id,
            callback=callback,
        )

    assert result.value == {"accepted": True}
    assert [asset.id for asset in artifact.assets] == ["figure-1"]
    assert artifact.assets[0].object_key.endswith("/figure-1.png")
    schedule_deletion.assert_called_once()
    assert schedule_deletion.call_args.kwargs["object_keys"] == {
        "documents/document-id/reflow/assets/old.png"
    }


def test_reflow_completion_rejects_changed_source_content() -> None:
    markdown = "# Paper\n\nSource paragraph."
    db, job, _artifact, document = _scope(markdown)
    callback = _completed_callback(job.id, document.id, markdown)
    assert callback.result is not None
    callback.result.source_hash = "f" * 64

    with patch(
        "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
        return_value=job,
    ):
        with pytest.raises(AppError) as raised:
            complete_document_reflow(
                db,
                actor=_actor(),
                job_id=job.id,
                callback=callback,
            )

    assert raised.value.code == "document_reflow_result_invalid"


def test_failed_reflow_does_not_change_document_processing_state() -> None:
    db, job, artifact, document = _scope()
    callback = DocumentReflowWebhookData(
        task_id=job.id,
        status="failed",
        error="document_reflow_failed",
    )
    failed_job = SimpleNamespace(status=JobStatus.FAILED.value)
    with (
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.fail",
            return_value=(failed_job, True),
        ),
    ):
        result = complete_document_reflow(
            db,
            actor=_actor(),
            job_id=job.id,
            callback=callback,
        )

    assert result.value == {"accepted": True}
    assert artifact.status == "failed"
    assert artifact.error_code == "document_reflow_failed"
    assert document.raw_content == "# Paper\n\nSource paragraph."
    assert isinstance(artifact.completed_at, datetime)
    assert artifact.completed_at.tzinfo is UTC


def test_reflow_completion_without_result_fails_job_instead_of_raising() -> None:
    db, job, artifact, document = _scope()
    callback = DocumentReflowWebhookData.model_construct(
        task_id=job.id,
        status="completed",
        result=None,
        usage_events=[],
    )
    failed_job = SimpleNamespace(status=JobStatus.FAILED.value)
    with (
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.fail",
            return_value=(failed_job, True),
        ),
    ):
        result = complete_document_reflow(
            db,
            actor=_actor(),
            job_id=job.id,
            callback=callback,
        )

    assert result.value == {"accepted": True}
    assert artifact.status == "failed"
    assert artifact.error_code == "document_reflow_result_missing"
    assert document.raw_content == "# Paper\n\nSource paragraph."


def test_asset_url_reauthorizes_paper_before_signing_derived_asset() -> None:
    document_id = uuid4()
    access = MagicMock(return_value=SimpleNamespace(title="Paper"))
    gateway = MagicMock()
    gateway.get_asset_url.return_value = DocumentReflowAssetUrlResponse(
        asset_id="figure-1",
        url="https://signed.example/figure-1.png",
        expires_in=900,
    )
    reflows = DocumentReflows(
        access=access,
        gateway=gateway,
        require_mineru=MagicMock(),
        journal=MagicMock(),
    )

    result = reflows.asset_url(
        actor=_actor(), document_id=document_id, asset_id="figure-1"
    )

    access.assert_called_once_with(actor=_actor(), document_id=document_id)
    gateway.get_asset_url.assert_called_once_with(
        document_id=document_id, asset_id="figure-1"
    )
    assert result.model_dump() == {
        "asset_id": "figure-1",
        "url": "https://signed.example/figure-1.png",
        "expires_in": 900,
    }
    assert "object_key" not in result.model_dump()
