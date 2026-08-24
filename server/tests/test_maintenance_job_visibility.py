"""Requester-facing job APIs must not expose operator maintenance work."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement

from app.bootstrap.adapters.paper_ingestion import SqlPaperIngestionGateway
from app.modules.jobs.infrastructure.repository import (
    JobRepository,
    requester_visible_job,
)
from app.shared.application import Actor
from app.shared.domain import AppError


def _sql(statement: ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_requester_visibility_predicate_is_additive_for_ordinary_jobs() -> None:
    sql = _sql(requester_visible_job())

    assert "payload ->> 'job_visibility'" in sql
    assert "IS DISTINCT FROM 'maintenance'" in sql


def test_requester_job_lists_apply_maintenance_visibility_filter() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    JobRepository.list_for_requester(db, requested_by_id=17)
    full_statement = db.scalars.call_args.args[0]
    JobRepository.list_statuses_for_requester(
        db,
        requested_by_id=17,
        limit=10,
    )
    status_statement = db.scalars.call_args.args[0]

    assert "IS DISTINCT FROM 'maintenance'" in _sql(full_statement)
    assert "IS DISTINCT FROM 'maintenance'" in _sql(status_statement)


def test_requester_cancel_hides_maintenance_but_worker_callback_does_not() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    job_id = uuid4()

    with pytest.raises(AppError) as cancelled:
        JobRepository.cancel(db, job_id=job_id, requested_by_id=17)
    cancel_statement = db.scalar.call_args.args[0]
    assert cancelled.value.code == "job_not_found"
    assert "IS DISTINCT FROM 'maintenance'" in _sql(cancel_statement)

    with pytest.raises(AppError) as claimed:
        JobRepository.claim_callback(db, job_id=job_id, requested_by_id=17)
    claim_statement = db.scalar.call_args.args[0]
    assert claimed.value.code == "job_not_found"
    assert "job_visibility" not in _sql(claim_statement)


@pytest.mark.parametrize("operation", ["retry", "cancel"])
def test_paper_ingestion_mutations_hide_maintenance_jobs(operation: str) -> None:
    db = MagicMock()
    db.scalar.return_value = None
    gateway = SqlPaperIngestionGateway(db)
    actor = Actor(
        id=17,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )

    with pytest.raises(AppError) as raised:
        if operation == "retry":
            gateway.retry_source(actor=actor, job_id=uuid4())
        else:
            gateway.cancel(
                actor=actor,
                job_id=uuid4(),
                correlation_id=uuid4(),
                origin_operation_id=uuid4(),
            )

    assert raised.value.code == "paper_ingestion_job_not_found"
    statement = db.scalar.call_args.args[0]
    assert "IS DISTINCT FROM 'maintenance'" in _sql(statement)
