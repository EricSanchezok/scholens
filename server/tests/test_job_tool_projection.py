from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.modules.jobs.application.contracts import JobListResponse, JobResponse
from app.modules.jobs.infrastructure.repository import JobRepository
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.modules.papers.application.contracts.uploads import UrlPaperSource
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError
from app.tooling import serialize_tool_success
from app.tooling.contracts import (
    DocumentSourceCandidate,
    ToolExecutionContext,
    ToolOutcome,
    ToolResourceLink,
)
from app.tooling.job_projection import (
    BATCH_INGESTION_OUTPUT_BYTES,
    LIST_JOBS_OUTPUT_BYTES,
    SINGLE_JOB_OUTPUT_BYTES,
    WAIT_FOR_JOBS_OUTPUT_BYTES,
    project_batch_paper_ingestion,
    project_get_job,
    project_list_jobs,
    project_retried_paper_ingestion,
    project_started_paper_ingestion,
    project_wait_for_jobs,
)
from app.tooling.workspace_contracts import (
    BatchPaperIngestionItem,
    BatchPaperIngestionResponse,
    BatchPaperIngestionSummary,
    JobBatchWaitMetadata,
    JobWaitMetadata,
    ListJobsInput,
    PaperIngestionToolResponse,
    WaitableJobResponse,
    WaitForJobsResponse,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

_NOW = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)


def _job(
    *,
    job_id: UUID | None = None,
    created_at: datetime = _NOW,
    result: dict[str, Any] | None = None,
) -> JobResponse:
    return JobResponse(
        id=job_id or uuid4(),
        operation="pdf_process",
        document_id=uuid4(),
        project_id=uuid4(),
        status="completed",
        progress_code=None,
        error_code=None,
        result=result,
        created_at=created_at,
        started_at=created_at,
        completed_at=created_at,
    )


def _waitable(job: JobResponse) -> WaitableJobResponse:
    return WaitableJobResponse(
        **job.model_dump(exclude={"result"}),
        result=None,
        wait=JobWaitMetadata(
            outcome="completed",
            requested_seconds=0,
            elapsed_ms=0,
            next_action="use_result",
            guidance="Continue with the resource identifier.",
        ),
    )


def _batch_wait() -> JobBatchWaitMetadata:
    return JobBatchWaitMetadata(
        outcome="all_terminal",
        requested_seconds=0,
        elapsed_ms=0,
        next_action="inspect_items",
        guidance="Continue with resource identifiers.",
    )


def _serialized_size(outcome: ToolOutcome) -> int:
    return serialize_tool_success(outcome).call_tool_result_utf8_bytes


def _context(*, actor_id: int = 7) -> ToolExecutionContext:
    operation_factory = OperationContextFactory()
    root = operation_factory.root(
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
            id=actor_id,
            email=f"reader-{actor_id}@example.com",
            status="active",
            email_verified=True,
        ),
        operation=operation_factory.child(
            root,
            initiated_by=OperationInitiator.AGENT,
        ),
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="job-projection-test",
        client_ip="test",
    )


def test_job_projectors_remove_results_from_current_and_legacy_shapes() -> None:
    secret = {"raw_content": "private full text", "provider_payload": {"x": 1}}
    job = _job(result=secret)
    waitable = _waitable(job)
    legacy_waitable = waitable.model_dump(mode="json")
    legacy_waitable["result"] = secret

    listed = project_list_jobs(
        ToolOutcome(
            payload=JobListResponse(items=[job], next_cursor="next").model_dump(
                mode="json"
            ),
            sources=(
                DocumentSourceCandidate(
                    document_id=job.document_id,
                    excerpt="private full text",
                ),
            ),
            artifacts=[{"raw_content": "private full text"}],
            action={"kind": "legacy", "result": secret},
            resource_links=(
                ToolResourceLink(
                    uri="https://storage.example.test/signed?secret=value",
                    name="legacy storage result",
                ),
            ),
        )
    )
    single = project_get_job(
        ToolOutcome(
            payload=legacy_waitable,
            action={"kind": "legacy", "result": secret},
        )
    )
    many = project_wait_for_jobs(
        ToolOutcome(
            payload=WaitForJobsResponse(
                items=[waitable],
                wait=_batch_wait(),
            ).model_dump(mode="json")
            | {"items": [legacy_waitable]},
            action={"kind": "legacy", "result": secret},
        )
    )

    assert JobListResponse.model_validate(listed.payload).items[0].result is None
    assert JobListResponse.model_validate(listed.payload).next_cursor == "next"
    assert WaitableJobResponse.model_validate(single.payload).result is None
    assert WaitForJobsResponse.model_validate(many.payload).items[0].result is None
    assert listed.action is None
    assert listed.sources == ()
    assert listed.artifacts == []
    assert listed.resource_links == ()
    assert single.action is None
    assert many.action is None


def test_mcp_job_schema_keeps_legacy_result_union_while_projection_nulls_value() -> (
    None
):
    public_result = WaitableJobResponse.model_json_schema()["properties"]["result"]
    internal_result = JobResponse.model_json_schema()["properties"]["result"]

    assert {branch.get("type") for branch in public_result["anyOf"]} == {
        "object",
        "null",
    }
    assert public_result == internal_result


def test_status_pages_and_wait_batches_stay_inside_their_utf8_budgets() -> None:
    jobs = [
        _job(
            created_at=_NOW + timedelta(seconds=index),
            result={"raw_content": "private" * 20_000},
        )
        for index in range(50)
    ]
    listed = project_list_jobs(
        ToolOutcome(
            payload=JobListResponse(items=jobs, next_cursor="opaque").model_dump(
                mode="json"
            )
        )
    )
    wait_payload = WaitForJobsResponse(
        items=[_waitable(job) for job in jobs],
        wait=_batch_wait(),
    ).model_dump(mode="json")
    for item, job in zip(wait_payload["items"], jobs, strict=True):
        item["result"] = job.result
    waited = project_wait_for_jobs(ToolOutcome(payload=wait_payload))

    assert _serialized_size(listed) <= LIST_JOBS_OUTPUT_BYTES
    assert _serialized_size(waited) <= WAIT_FOR_JOBS_OUTPUT_BYTES
    assert waited.resource_links == ()


@pytest.mark.parametrize(
    ("projector", "action_kind"),
    [
        (project_started_paper_ingestion, "paper_ingestion_started"),
        (project_retried_paper_ingestion, "paper_ingestion_retried"),
    ],
)
def test_ingestion_projectors_emit_compact_actions(
    projector: Any,
    action_kind: str,
) -> None:
    job = _job(result={"raw_content": "secret"})
    response = PaperIngestionToolResponse(
        id=uuid4(),
        display_name="😀" * 5_000,
        source_kind="url",
        state="queued",
        stage="queued",
        project_id=job.project_id,
        document_id=job.document_id,
        created_at=_NOW,
        job=_waitable(job),
    )

    legacy_payload = response.model_dump(mode="json")
    legacy_payload["job"]["result"] = {"raw_content": "secret"}
    outcome = projector(
        ToolOutcome(
            payload=legacy_payload,
            action={"kind": "legacy", "result": {"raw_content": "secret"}},
        )
    )
    projected = PaperIngestionToolResponse.model_validate(outcome.payload)

    assert projected.job.result is None
    assert len(projected.display_name.encode("utf-8")) <= 512
    assert "\ufffd" not in projected.display_name
    assert outcome.action == {
        "kind": action_kind,
        "job_id": str(job.id),
        "document_id": str(job.document_id),
        "project_id": str(job.project_id),
        "status": "completed",
    }
    assert {link.uri for link in outcome.resource_links} == {
        f"scholens://papers/{job.document_id}",
        f"scholens://projects/{job.project_id}",
    }
    assert _serialized_size(outcome) <= SINGLE_JOB_OUTPUT_BYTES


@pytest.mark.parametrize(
    "original_source",
    [
        "😀" * 2_048,
        '\x00\x01"\\🙂' * 100,
    ],
)
def test_batch_projection_stays_bounded_for_fifty_worst_case_json_items(
    original_source: str,
) -> None:
    items: list[BatchPaperIngestionItem] = []
    links: list[ToolResourceLink] = []
    for index in range(50):
        job = _job(result={"raw_content": "secret" * 20_000})
        ingestion = LibraryPaperIngestionResponse(
            id=uuid4(),
            display_name=original_source * 10,
            source_kind="url",
            state="queued",
            stage="queued",
            project_id=job.project_id,
            document_id=job.document_id,
            created_at=_NOW,
        )
        items.append(
            BatchPaperIngestionItem(
                index=index,
                source=UrlPaperSource(url=original_source),
                status="accepted",
                ingestion=ingestion,
                job=_waitable(job),
            )
        )
        links.append(
            ToolResourceLink(
                uri=f"scholens://papers/{job.document_id}",
                name=f"Paper {job.document_id}",
                description="Canonical paper resource.",
            )
        )
    response = BatchPaperIngestionResponse(
        items=items,
        summary=BatchPaperIngestionSummary(
            requested=50,
            accepted=50,
            rejected=0,
            active=0,
            completed=50,
            failed=0,
            cancelled=0,
        ),
        wait=_batch_wait(),
    )
    legacy_payload = response.model_dump(mode="json")
    for item in legacy_payload["items"]:
        item["job"]["result"] = {"raw_content": "secret" * 20_000}
    unprojected = ToolOutcome(
        payload=legacy_payload,
        action={"kind": "legacy", "result": {"raw_content": "secret" * 20_000}},
        resource_links=tuple(links),
    )

    outcome = project_batch_paper_ingestion(unprojected)
    projected = BatchPaperIngestionResponse.model_validate(outcome.payload)

    assert all(item.source_truncated for item in projected.items)
    assert all(
        len(item.source.url.encode("utf-8")) <= 512
        for item in projected.items
        if item.source.kind == "url"
    )
    assert all(
        item.ingestion is not None
        and len(item.ingestion.display_name.encode("utf-8")) <= 512
        and item.job is not None
        and item.job.result is None
        for item in projected.items
    )
    assert "\ufffd" not in str(outcome.payload)
    assert response.items[0].source.url == original_source
    assert _serialized_size(outcome) <= BATCH_INGESTION_OUTPUT_BYTES
    assert outcome.resource_links == ()
    assert outcome.action is not None
    assert set(outcome.action) == {
        "kind",
        "requested",
        "accepted",
        "rejected",
        "active",
        "job_ids",
    }


class _StatusJobs:
    def __init__(self, jobs: list[JobResponse]) -> None:
        self.jobs = jobs
        self.calls: list[dict[str, Any]] = []

    def list_statuses(self, **kwargs: Any) -> list[JobResponse]:
        self.calls.append(kwargs)
        before = (
            (kwargs["before_created_at"], kwargs["before_id"])
            if kwargs["before_created_at"] is not None
            else None
        )
        jobs = self.jobs
        if before is not None:
            jobs = [job for job in jobs if (job.created_at, job.id) < before]
        return jobs[: kwargs["limit"]]


def _handlers() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=object(),  # type: ignore[arg-type]
        ingestion=object(),  # type: ignore[arg-type]
        citations=object(),  # type: ignore[arg-type]
        web_base_url="https://scholens.test",
        cursor_secret="job-cursor-secret",
    )


def test_list_jobs_uses_keyset_cursor_bound_to_actor_and_filters() -> None:
    jobs = [
        _job(created_at=_NOW + timedelta(minutes=offset), result=None)
        for offset in (3, 2, 1)
    ]
    status_jobs = _StatusJobs(jobs)
    capabilities = type("Capabilities", (), {"jobs": status_jobs})()
    handlers = _handlers()
    context = _context()

    first = JobListResponse.model_validate(
        handlers.list_jobs(
            capabilities,  # type: ignore[arg-type]
            context,
            ListJobsInput(limit=2),
        ).payload
    )
    assert [job.id for job in first.items] == [jobs[0].id, jobs[1].id]
    assert first.next_cursor is not None
    assert status_jobs.calls[0]["limit"] == 3

    second = JobListResponse.model_validate(
        handlers.list_jobs(
            capabilities,  # type: ignore[arg-type]
            context,
            ListJobsInput(limit=2, cursor=first.next_cursor),
        ).payload
    )
    assert [job.id for job in second.items] == [jobs[2].id]
    assert second.next_cursor is None
    assert status_jobs.calls[1]["before_created_at"] == jobs[1].created_at
    assert status_jobs.calls[1]["before_id"] == jobs[1].id

    with pytest.raises(AppError) as changed_filter:
        handlers.list_jobs(
            capabilities,  # type: ignore[arg-type]
            context,
            ListJobsInput(limit=2, active=True, cursor=first.next_cursor),
        )
    assert changed_filter.value.code == "job_cursor_invalid"

    with pytest.raises(AppError) as changed_actor:
        handlers.list_jobs(
            capabilities,  # type: ignore[arg-type]
            _context(actor_id=8),
            ListJobsInput(limit=2, cursor=first.next_cursor),
        )
    assert changed_actor.value.code == "job_cursor_invalid"


def test_status_query_does_not_select_job_payload_or_result_json() -> None:
    db = MagicMock(spec=Session)
    db.scalars.return_value.all.return_value = []

    JobRepository.list_statuses_for_requester(
        db,
        requested_by_id=7,
        before_created_at=_NOW,
        before_id=uuid4(),
        limit=21,
    )

    statement = db.scalars.call_args.args[0]
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).split()).lower()
    selected = sql.split(" from ", maxsplit=1)[0]
    assert ".payload" not in selected
    assert ".result" not in selected
    assert ".idempotency_key" not in selected
    assert ".created_at desc" in sql
    assert ".id desc" in sql

    job_id = uuid4()
    db.reset_mock()
    db.scalars.return_value.all.return_value = [type("StatusRow", (), {"id": job_id})()]
    JobRepository.require_many_statuses_for_requester(
        db,
        requested_by_id=7,
        job_ids=(job_id,),
    )
    batch_statement = db.scalars.call_args.args[0]
    batch_sql = " ".join(
        str(batch_statement.compile(dialect=postgresql.dialect())).split()
    ).lower()
    batch_selected = batch_sql.split(" from ", maxsplit=1)[0]
    assert ".payload" not in batch_selected
    assert ".result" not in batch_selected
