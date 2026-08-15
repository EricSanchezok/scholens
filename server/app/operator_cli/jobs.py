"""Read-only durable job inspection."""

from __future__ import annotations

from uuid import UUID

import click
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.operator_cli.common import CliState, OutputGroup, emit, guarded


def _projection(job: object) -> dict[str, object]:
    from app.database.models import DurableJob

    assert isinstance(job, DurableJob)
    dispatch = job.dispatch
    return {
        "id": job.id,
        "operation": job.operation,
        "status": job.status,
        "progress_code": job.progress_code,
        "error_code": job.error_code,
        "attempt_count": job.attempt_count,
        "requested_by_id": job.requested_by_id,
        "project_id": job.project_id,
        "document_id": job.document_id,
        "correlation_id": job.correlation_id,
        "origin_operation_id": job.origin_operation_id,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "dispatch": (
            None
            if dispatch is None
            else {
                "status": dispatch.status,
                "attempt_count": dispatch.attempt_count,
                "last_error_code": dispatch.last_error_code,
                "available_at": dispatch.available_at,
                "published_at": dispatch.published_at,
            }
        ),
    }


@click.group("jobs", cls=OutputGroup)
def jobs_group() -> None:
    """Inspect safe job projections; job state cannot be changed here."""


def _list_jobs(*, status: str | None, limit: int) -> list[dict[str, object]]:
    from app.database.database import SessionLocal
    from app.database.models import DurableJob

    with SessionLocal() as db:
        statement = select(DurableJob).options(joinedload(DurableJob.dispatch))
        if status is not None:
            statement = statement.where(DurableJob.status == status)
        jobs = list(
            db.scalars(statement.order_by(DurableJob.created_at.desc()).limit(limit))
        )
        return [_projection(job) for job in jobs]


@jobs_group.command("list")
@click.option("--status", default=None)
@click.option("--limit", type=click.IntRange(1, 500), default=100, show_default=True)
@click.pass_obj
@guarded
def list_jobs(state: CliState, status: str | None, limit: int) -> None:
    rows = _list_jobs(status=status, limit=limit)
    emit(
        state,
        rows,
        human="\n".join(
            f"{row['id']}\t{row['status']}\t{row['operation']}" for row in rows
        ),
    )


@jobs_group.command("failures")
@click.option("--limit", type=click.IntRange(1, 500), default=100, show_default=True)
@click.pass_obj
@guarded
def list_failures(state: CliState, limit: int) -> None:
    rows = _list_jobs(status="failed", limit=limit)
    emit(
        state,
        rows,
        human="\n".join(
            f"{row['id']}\t{row['error_code']}\t{row['operation']}" for row in rows
        ),
    )


@jobs_group.command("show")
@click.argument("job_id", type=click.UUID)
@click.pass_obj
@guarded
def show_job(state: CliState, job_id: UUID) -> None:
    from app.database.database import SessionLocal
    from app.database.models import DurableJob

    with SessionLocal() as db:
        job = db.scalar(
            select(DurableJob)
            .options(joinedload(DurableJob.dispatch))
            .where(DurableJob.id == job_id)
        )
        if job is None:
            raise click.ClickException(f"Job {job_id} was not found.")
        payload = _projection(job)
    emit(state, payload)


__all__ = ["jobs_group"]
