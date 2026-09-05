from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from app.modules.jobs.application.contracts import JobResponse
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.modules.papers.application.contracts.uploads import DoiPaperSource, PaperSource
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind
from app.tooling.contracts import ToolExecutionContext, ToolOutcome
from app.tooling.workspace_contracts import (
    BatchPaperIngestionResponse,
    GetJobInput,
    IngestPaperInput,
    IngestPapersInput,
    WaitForJobsInput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers


class _Ingestion:
    def __init__(self, *, rejected_doi: str | None = None) -> None:
        self.rejected_doi = rejected_doi
        self.calls: list[tuple[str, str]] = []
        self.jobs: dict[UUID, LibraryPaperIngestionResponse] = {}
        self.active = 0
        self.max_active = 0

    async def from_source(self, **kwargs: Any) -> LibraryPaperIngestionResponse:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            value = str(kwargs["value"])
            if value == self.rejected_doi:
                raise AppError(
                    code="paper_source_invalid",
                    message="invalid source",
                    kind=FailureKind.INVALID_ARGUMENT,
                )
            self.calls.append((value, str(kwargs["idempotency_key"])))
            result = LibraryPaperIngestionResponse(
                id=uuid4(),
                display_name=value,
                source_kind="doi",
                state="queued",
                stage="queued",
                project_id=kwargs["project_id"],
                document_id=uuid4(),
                created_at=datetime.now(UTC),
            )
            self.jobs[result.id] = result
            return result
        finally:
            self.active -= 1

    async def from_upload_session(self, **_kwargs: Any) -> Any:
        raise AssertionError("upload path not expected")


class _Jobs:
    def __init__(self, ingestion: _Ingestion) -> None:
        self._ingestion = ingestion
        self.calls: list[tuple[UUID, ...]] = []

    def get_many_statuses(
        self, *, actor: Actor, job_ids: tuple[UUID, ...]
    ) -> list[JobResponse]:
        assert actor.id == 7
        self.calls.append(job_ids)
        now = datetime.now(UTC)
        return [
            JobResponse(
                id=job_id,
                operation="pdf_process",
                document_id=self._ingestion.jobs[job_id].document_id,
                project_id=self._ingestion.jobs[job_id].project_id,
                status="pending",
                progress_code=None,
                error_code=None,
                result=None,
                created_at=now,
                started_at=None,
                completed_at=None,
            )
            for job_id in job_ids
        ]


class _Executor:
    def __init__(self, jobs: _Jobs) -> None:
        self.capabilities = type("Capabilities", (), {"jobs": jobs})()

    def query(self, operation: Any) -> Any:
        return operation(self.capabilities)


def _context() -> ToolExecutionContext:
    operation_factory = OperationContextFactory()
    request_operation = operation_factory.root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=RequestReference(uuid4()),
            conversation_id=uuid4(),
            turn_id=uuid4(),
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=Actor(
            id=7,
            email="reader@example.com",
            status="active",
            email_verified=True,
        ),
        operation=operation_factory.child(
            request_operation,
            initiated_by=OperationInitiator.AGENT,
        ),
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="batch-ingestion-test",
        client_ip="test",
    )


def _handler(ingestion: _Ingestion, jobs: _Jobs) -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=_Executor(jobs),  # type: ignore[arg-type]
        ingestion=ingestion,  # type: ignore[arg-type]
        citations=object(),  # type: ignore[arg-type]
        web_base_url="https://scholens.test",
        cursor_secret="test-secret",
    )


def _finalize_outcome(outcome: ToolOutcome) -> ToolOutcome:
    return outcome


def test_wait_defaults_and_upper_bound_are_explicit() -> None:
    job_id = uuid4()

    assert IngestPaperInput(source=DoiPaperSource(doi="10.1000/one")).wait_seconds == 30
    assert GetJobInput(job_id=job_id).wait_seconds == 30
    assert WaitForJobsInput(job_ids=[job_id]).wait_seconds == 30
    assert GetJobInput(job_id=job_id, wait_seconds=0).wait_seconds == 0
    with pytest.raises(ValidationError):
        GetJobInput(job_id=job_id, wait_seconds=241)


@pytest.mark.asyncio
async def test_batch_ingestion_accepts_thirty_sources_with_one_batched_job_read() -> (
    None
):
    ingestion = _Ingestion()
    jobs = _Jobs(ingestion)
    sources: list[PaperSource] = [
        DoiPaperSource(doi=f"10.1000/{index}") for index in range(30)
    ]

    outcome = await _handler(ingestion, jobs).ingest_papers(
        _context(),
        IngestPapersInput(sources=sources, wait_seconds=0),
        "batch-invocation",
        _finalize_outcome,
    )

    payload = BatchPaperIngestionResponse.model_validate(outcome.payload)
    assert payload.summary.model_dump() == {
        "requested": 30,
        "accepted": 30,
        "rejected": 0,
        "active": 30,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert [item.index for item in payload.items] == list(range(30))
    assert all(
        item.job is not None and item.job.wait.outcome == "timed_out"
        for item in payload.items
    )
    assert ingestion.max_active == 4
    assert len({idempotency_key for _, idempotency_key in ingestion.calls}) == 30
    assert len(jobs.calls) == 1
    assert len(jobs.calls[0]) == 30
    assert outcome.action is not None
    assert outcome.action["kind"] == "paper_ingestions_started"


@pytest.mark.asyncio
async def test_batch_ingestion_preserves_partial_success() -> None:
    ingestion = _Ingestion(rejected_doi="10.1000/bad")
    jobs = _Jobs(ingestion)

    outcome = await _handler(ingestion, jobs).ingest_papers(
        _context(),
        IngestPapersInput(
            sources=[
                DoiPaperSource(doi="10.1000/good"),
                DoiPaperSource(doi="10.1000/bad"),
            ],
            wait_seconds=0,
        ),
        "partial-batch",
        _finalize_outcome,
    )

    payload = BatchPaperIngestionResponse.model_validate(outcome.payload)
    assert payload.summary.accepted == 1
    assert payload.summary.rejected == 1
    assert payload.items[0].status == "accepted"
    assert payload.items[1].model_dump(mode="json") == {
        "index": 1,
        "source": {"kind": "doi", "doi": "10.1000/bad"},
        "source_truncated": False,
        "status": "rejected",
        "ingestion": None,
        "job": None,
        "error_code": "paper_source_invalid",
    }
