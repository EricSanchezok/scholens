from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.modules.jobs.application.contracts import JobResponse
from app.shared.application import Actor
from app.tooling.job_waiting import JobWaiter


@dataclass
class _Clock:
    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Jobs:
    def __init__(self, clock: _Clock, transitions: dict[UUID, float | None]) -> None:
        self._clock = clock
        self._transitions = transitions
        self.calls: list[tuple[UUID, ...]] = []

    def get_many(self, *, actor: Actor, job_ids: tuple[UUID, ...]) -> list[JobResponse]:
        assert actor.id == 7
        self.calls.append(job_ids)
        return [
            _job(
                job_id,
                status=(
                    "completed"
                    if (transition := self._transitions[job_id]) is not None
                    and self._clock.now >= transition
                    else "running"
                ),
            )
            for job_id in job_ids
        ]


class _Executor:
    def __init__(self, jobs: _Jobs) -> None:
        self.capabilities = type("Capabilities", (), {"jobs": jobs})()

    def query(self, operation: Any) -> Any:
        return operation(self.capabilities)


def _job(job_id: UUID, *, status: str) -> JobResponse:
    now = datetime.now(UTC)
    return JobResponse(
        id=job_id,
        operation="pdf_process",
        document_id=None,
        project_id=None,
        status=status,
        progress_code="parsing" if status == "running" else None,
        error_code=None,
        result={"document_id": str(uuid4())} if status == "completed" else None,
        created_at=now,
        started_at=now,
        completed_at=now if status == "completed" else None,
    )


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _waiter(clock: _Clock, jobs: _Jobs) -> JobWaiter:
    return JobWaiter(
        executor=_Executor(jobs),  # type: ignore[arg-type]
        clock=clock.monotonic,
        sleep=clock.sleep,
        jitter=lambda _start, _end: 0.0,
    )


@pytest.mark.asyncio
async def test_wait_for_one_returns_immediately_when_terminal() -> None:
    clock = _Clock(now=5.0)
    job_id = uuid4()
    jobs = _Jobs(clock, {job_id: 0.0})

    result = await _waiter(clock, jobs).wait_for_one(
        actor=_actor(), job_id=job_id, wait_seconds=30
    )

    assert result.status == "completed"
    assert result.wait.outcome == "completed"
    assert result.wait.next_action == "use_result"
    assert result.wait.elapsed_ms == 0
    assert jobs.calls == [(job_id,)]


@pytest.mark.asyncio
async def test_wait_for_many_uses_one_batch_query_per_poll_and_preserves_order() -> (
    None
):
    clock = _Clock()
    first = uuid4()
    second = uuid4()
    jobs = _Jobs(clock, {first: 1.5, second: 3.5})

    result = await _waiter(clock, jobs).wait_for_many(
        actor=_actor(), job_ids=(second, first), wait_seconds=30
    )

    assert [item.id for item in result.items] == [second, first]
    assert [item.status for item in result.items] == ["completed", "completed"]
    assert result.wait.outcome == "all_terminal"
    assert result.wait.elapsed_ms == 3500
    assert jobs.calls == [(second, first)] * 4


@pytest.mark.asyncio
async def test_wait_for_many_times_out_with_final_snapshot_and_guidance() -> None:
    clock = _Clock()
    job_id = uuid4()
    jobs = _Jobs(clock, {job_id: None})

    result = await _waiter(clock, jobs).wait_for_many(
        actor=_actor(), job_ids=(job_id,), wait_seconds=3
    )

    assert result.wait.outcome == "timed_out"
    assert result.wait.next_action == "wait_for_remaining"
    assert result.wait.elapsed_ms == 3000
    assert result.items[0].wait.outcome == "timed_out"
    assert result.items[0].wait.next_action == "wait_again"
    assert "rapid" in result.items[0].wait.guidance
    assert len(jobs.calls) == 4


@pytest.mark.asyncio
async def test_wait_propagates_cancellation_without_extra_query() -> None:
    clock = _Clock()
    job_id = uuid4()
    jobs = _Jobs(clock, {job_id: None})

    async def cancel_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    waiter = JobWaiter(
        executor=_Executor(jobs),  # type: ignore[arg-type]
        clock=clock.monotonic,
        sleep=cancel_sleep,
        jitter=lambda _start, _end: 0.0,
    )

    with pytest.raises(asyncio.CancelledError):
        await waiter.wait_for_one(actor=_actor(), job_id=job_id, wait_seconds=30)

    assert jobs.calls == [(job_id,)]
