"""Bounded Agent-facing projections for durable Job tool outcomes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from uuid import UUID

from app.modules.jobs.application.contracts import JobListResponse, JobResponse
from app.modules.papers.application.contracts.uploads import PaperSource
from app.shared.application.text import json_bounded_prefix
from app.shared.domain import JsonValue
from app.tooling import workspace_contracts as wc
from app.tooling.contracts import ToolOutcome, ToolResourceLink

SINGLE_JOB_OUTPUT_BYTES = 32 * 1024
LIST_JOBS_OUTPUT_BYTES = 64 * 1024
WAIT_FOR_JOBS_OUTPUT_BYTES = 96 * 1024
BATCH_INGESTION_OUTPUT_BYTES = 192 * 1024
_MAX_DISPLAY_NAME_JSON_BYTES = 256
_MAX_SOURCE_REFERENCE_JSON_BYTES = 256
_JsonProjector = Callable[[JsonValue], JsonValue]


def _project_object_field(
    value: JsonValue,
    *,
    field: str,
    projector: _JsonProjector,
) -> JsonValue:
    if not isinstance(value, dict):
        return value
    projected = dict(value)
    nested = projected.get(field)
    if nested is not None:
        projected[field] = projector(nested)
    return projected


def _project_list_field(
    value: JsonValue,
    *,
    field: str,
    projector: _JsonProjector,
) -> JsonValue:
    if not isinstance(value, dict):
        return value
    projected = dict(value)
    nested = projected.get(field)
    if isinstance(nested, list):
        projected[field] = [projector(item) for item in nested]
    return projected


def _without_job_result(value: JsonValue) -> JsonValue:
    if not isinstance(value, dict):
        return value
    return {**value, "result": None}


def _without_nested_job_result(value: JsonValue) -> JsonValue:
    return _project_object_field(
        value,
        field="job",
        projector=_without_job_result,
    )


def _resource_links(
    *,
    document_id: UUID | None,
    project_id: UUID | None,
) -> tuple[ToolResourceLink, ...]:
    links: list[ToolResourceLink] = []
    if document_id is not None:
        links.append(
            ToolResourceLink(
                uri=f"scholens://papers/{document_id}",
                name=f"Paper {document_id}",
                description=(
                    "Canonical Scholens paper metadata. Use get_paper_content for "
                    "bounded text."
                ),
            )
        )
    if project_id is not None:
        links.append(
            ToolResourceLink(
                uri=f"scholens://projects/{project_id}",
                name=f"Project {project_id}",
                description=(
                    "Bounded Project manifest for restoring a long-running research "
                    "context."
                ),
            )
        )
    return tuple(links)


def _job_resource_links(job: JobResponse) -> tuple[ToolResourceLink, ...]:
    return _resource_links(
        document_id=job.document_id,
        project_id=job.project_id,
    )


def _waitable_status_only(job: wc.WaitableJobResponse) -> wc.WaitableJobResponse:
    return job.model_copy(update={"result": None})


def _bounded_json_text(value: str, *, max_bytes: int) -> tuple[str, bool]:
    bounded = json_bounded_prefix(value, max_bytes=max_bytes)
    return bounded, bounded != value


def _bounded_display_name(value: str) -> str:
    return _bounded_json_text(
        value,
        max_bytes=_MAX_DISPLAY_NAME_JSON_BYTES,
    )[0]


def _bounded_source(source: PaperSource) -> tuple[PaperSource, bool]:
    if source.kind == "upload":
        return source, False
    field_name = {
        "doi": "doi",
        "arxiv": "arxiv_id",
        "url": "url",
    }[source.kind]
    value = getattr(source, field_name)
    bounded, truncated = _bounded_json_text(
        value,
        max_bytes=_MAX_SOURCE_REFERENCE_JSON_BYTES,
    )
    return source.model_copy(update={field_name: bounded}), truncated


def project_list_jobs(outcome: ToolOutcome) -> ToolOutcome:
    payload = _project_list_field(
        outcome.payload,
        field="items",
        projector=_without_job_result,
    )
    response = JobListResponse.model_validate(payload)
    return replace(
        outcome,
        payload=response.model_dump(mode="json"),
        sources=(),
        artifacts=[],
        action=None,
        resource_links=(),
    )


def project_get_job(outcome: ToolOutcome) -> ToolOutcome:
    response = wc.WaitableJobResponse.model_validate(
        _without_job_result(outcome.payload)
    )
    projected = _waitable_status_only(response)
    return replace(
        outcome,
        payload=projected.model_dump(mode="json"),
        sources=(),
        artifacts=[],
        action=None,
        resource_links=_job_resource_links(projected),
    )


def project_wait_for_jobs(outcome: ToolOutcome) -> ToolOutcome:
    payload = _project_list_field(
        outcome.payload,
        field="items",
        projector=_without_job_result,
    )
    response = wc.WaitForJobsResponse.model_validate(payload)
    projected = response.model_copy(
        update={"items": [_waitable_status_only(job) for job in response.items]}
    )
    return replace(
        outcome,
        payload=projected.model_dump(mode="json"),
        sources=(),
        artifacts=[],
        action=None,
        resource_links=(),
    )


def project_paper_ingestion(
    outcome: ToolOutcome,
    *,
    action_kind: str,
) -> ToolOutcome:
    response = wc.PaperIngestionToolResponse.model_validate(
        _without_nested_job_result(outcome.payload)
    )
    projected = response.model_copy(
        update={
            "display_name": _bounded_display_name(response.display_name),
            "job": _waitable_status_only(response.job),
        }
    )
    action: dict[str, JsonValue] = {
        "kind": action_kind,
        "job_id": str(projected.job.id),
        "document_id": (
            str(projected.document_id) if projected.document_id is not None else None
        ),
        "project_id": (
            str(projected.project_id) if projected.project_id is not None else None
        ),
        "status": projected.job.status,
    }
    return replace(
        outcome,
        payload=projected.model_dump(mode="json"),
        sources=(),
        artifacts=[],
        action=action,
        resource_links=_job_resource_links(projected.job),
    )


def project_started_paper_ingestion(outcome: ToolOutcome) -> ToolOutcome:
    return project_paper_ingestion(
        outcome,
        action_kind="paper_ingestion_started",
    )


def project_retried_paper_ingestion(outcome: ToolOutcome) -> ToolOutcome:
    return project_paper_ingestion(
        outcome,
        action_kind="paper_ingestion_retried",
    )


def project_batch_paper_ingestion(outcome: ToolOutcome) -> ToolOutcome:
    payload = _project_list_field(
        outcome.payload,
        field="items",
        projector=_without_nested_job_result,
    )
    response = wc.BatchPaperIngestionResponse.model_validate(payload)
    items: list[wc.BatchPaperIngestionItem] = []
    for item in response.items:
        source, source_truncated = _bounded_source(item.source)
        items.append(
            item.model_copy(
                update={
                    "source": source,
                    "source_truncated": item.source_truncated or source_truncated,
                    "ingestion": (
                        item.ingestion.model_copy(
                            update={
                                "display_name": _bounded_display_name(
                                    item.ingestion.display_name
                                )
                            }
                        )
                        if item.ingestion is not None
                        else None
                    ),
                    "job": (
                        _waitable_status_only(item.job)
                        if item.job is not None
                        else None
                    ),
                }
            )
        )
    projected = response.model_copy(update={"items": items})
    job_ids: list[JsonValue] = [
        str(item.job.id) for item in items if item.job is not None
    ]
    action: dict[str, JsonValue] = {
        "kind": "paper_ingestions_started",
        "requested": projected.summary.requested,
        "accepted": projected.summary.accepted,
        "rejected": projected.summary.rejected,
        "active": projected.summary.active,
        "job_ids": job_ids,
    }
    return replace(
        outcome,
        payload=projected.model_dump(mode="json"),
        sources=(),
        artifacts=[],
        action=action,
        resource_links=(),
    )


__all__ = [
    "BATCH_INGESTION_OUTPUT_BYTES",
    "LIST_JOBS_OUTPUT_BYTES",
    "SINGLE_JOB_OUTPUT_BYTES",
    "WAIT_FOR_JOBS_OUTPUT_BYTES",
    "project_batch_paper_ingestion",
    "project_get_job",
    "project_list_jobs",
    "project_retried_paper_ingestion",
    "project_started_paper_ingestion",
    "project_wait_for_jobs",
]
