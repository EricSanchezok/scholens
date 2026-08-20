"""Cancellation-aware bounded observation of durable jobs for model-visible tools."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.jobs.application.contracts import JobResponse
from app.shared.application import Actor, ApplicationExecutor
from app.tooling.workspace_contracts import (
    JobBatchWaitMetadata,
    JobWaitMetadata,
    WaitableJobResponse,
    WaitForJobsResponse,
)
from scholens_observability import add_counter, record_histogram

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_INITIAL_POLL_SECONDS = 0.5
_MAX_POLL_SECONDS = 5.0
_JITTER_RATIO = 0.1


def _job_wait_metadata(
    job: JobResponse,
    *,
    requested_seconds: int,
    elapsed_ms: int,
) -> JobWaitMetadata:
    if job.status == "completed":
        return JobWaitMetadata(
            outcome="completed",
            requested_seconds=requested_seconds,
            elapsed_ms=elapsed_ms,
            next_action="use_result",
            guidance="Use the completed job result; no further status call is needed.",
        )
    if job.status == "failed":
        return JobWaitMetadata(
            outcome="failed",
            requested_seconds=requested_seconds,
            elapsed_ms=elapsed_ms,
            next_action="inspect_failure",
            guidance=(
                "Inspect the stable error code and retry only when the operation's "
                "failure contract says it is retryable."
            ),
        )
    if job.status == "cancelled":
        return JobWaitMetadata(
            outcome="cancelled",
            requested_seconds=requested_seconds,
            elapsed_ms=elapsed_ms,
            next_action="stop",
            guidance="The job was cancelled; do not wait or retry it automatically.",
        )
    return JobWaitMetadata(
        outcome="timed_out",
        requested_seconds=requested_seconds,
        elapsed_ms=elapsed_ms,
        next_action="wait_again",
        guidance=(
            "The durable job is still active. Wait again for this job instead of "
            "rapidly polling its status."
        ),
    )


class JobWaiter:
    """Poll durable snapshots without retaining a transaction between observations."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._executor = executor
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter

    async def wait_for_one(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        wait_seconds: int,
    ) -> WaitableJobResponse:
        result = await self.wait_for_many(
            actor=actor,
            job_ids=(job_id,),
            wait_seconds=wait_seconds,
        )
        return result.items[0]

    async def wait_for_many(
        self,
        *,
        actor: Actor,
        job_ids: Sequence[UUID],
        wait_seconds: int,
    ) -> WaitForJobsResponse:
        ordered_ids = tuple(job_ids)
        if not ordered_ids:
            raise ValueError("job_ids must not be empty")
        started = self._clock()
        deadline = started + wait_seconds
        poll_count = 0
        jobs = await self._load(actor=actor, job_ids=ordered_ids)
        poll_count += 1
        last_observed_at = self._clock()
        delay = _INITIAL_POLL_SECONDS

        while not self._all_terminal(jobs):
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            jittered_delay = delay * (1.0 + self._jitter(-_JITTER_RATIO, _JITTER_RATIO))
            await self._sleep(min(max(jittered_delay, 0.0), remaining))
            jobs = await self._load(actor=actor, job_ids=ordered_ids)
            poll_count += 1
            last_observed_at = self._clock()
            delay = min(delay * 2, _MAX_POLL_SECONDS)

        if not self._all_terminal(jobs) and last_observed_at < deadline:
            jobs = await self._load(actor=actor, job_ids=ordered_ids)
            poll_count += 1

        elapsed_ms = max(0, round((self._clock() - started) * 1000))
        all_terminal = self._all_terminal(jobs)
        wait = JobBatchWaitMetadata(
            outcome="all_terminal" if all_terminal else "timed_out",
            requested_seconds=wait_seconds,
            elapsed_ms=elapsed_ms,
            next_action="inspect_items" if all_terminal else "wait_for_remaining",
            guidance=(
                "Inspect each terminal job result; no further wait is needed."
                if all_terminal
                else (
                    "Wait again for only the active job IDs. Do not issue rapid "
                    "status polls."
                )
            ),
        )
        items = [
            WaitableJobResponse(
                **job.model_dump(),
                wait=_job_wait_metadata(
                    job,
                    requested_seconds=wait_seconds,
                    elapsed_ms=elapsed_ms,
                ),
            )
            for job in jobs
        ]
        outcome = wait.outcome
        attributes = {
            "outcome": outcome,
            "cardinality": "single" if len(ordered_ids) == 1 else "batch",
        }
        add_counter("scholens.tool.job_waits", attributes=attributes)
        add_counter(
            "scholens.tool.job_wait_polls",
            value=poll_count,
            attributes=attributes,
        )
        record_histogram(
            "scholens.tool.job_wait_duration",
            elapsed_ms,
            attributes=attributes,
        )
        return WaitForJobsResponse(items=items, wait=wait)

    async def _load(
        self,
        *,
        actor: Actor,
        job_ids: tuple[UUID, ...],
    ) -> list[JobResponse]:
        return await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.jobs.get_many(
                actor=actor,
                job_ids=job_ids,
            ),
        )

    @staticmethod
    def _all_terminal(jobs: Sequence[JobResponse]) -> bool:
        return all(job.status in _TERMINAL_STATUSES for job in jobs)


__all__ = ["JobWaiter"]
