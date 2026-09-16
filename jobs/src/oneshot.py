"""Bounded, broker-settled Celery lifecycle for admitted ECS RunTask workers."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from celery import Task, bootsteps, signals
from celery.worker import state as worker_state
from celery.worker.request import Request


@dataclass
class DrainState:
    started: float
    max_tasks: int = 1
    max_seconds: float = 300
    received_count: int = 0
    settled_count: int = 0
    first_received: float | None = None
    last_settled: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.max_tasks <= 5 or not 1 <= self.max_seconds <= 300:
            raise ValueError(
                "Worker drain must be bounded to five tasks and 300 seconds"
            )

    def received(self, *, now: float | None = None) -> None:
        self.received_count += 1
        if self.first_received is None:
            self.first_received = time.monotonic() if now is None else now

    def settled(self, *, now: float | None = None) -> None:
        self.settled_count += 1
        self.last_settled = time.monotonic() if now is None else now

    def stop_consuming(self, *, now: float) -> bool:
        return self.received_count >= self.max_tasks or (
            self.first_received is not None
            and now - self.first_received >= self.max_seconds
        )

    def should_exit(self, *, now: float) -> bool:
        if self.received_count > self.settled_count:
            return False
        idle_since = (
            self.last_settled if self.last_settled is not None else self.started
        )
        return self.stop_consuming(now=now) or now - idle_since >= 30


drain = DrainState(started=time.monotonic())


class OneShotRequest(Request):
    """Observe acknowledgement in the parent, never in task_postrun's child."""

    def acknowledge(self) -> None:
        pending = not self.acknowledged
        super().acknowledge()
        if pending and self.acknowledged:
            drain.settled()

    def reject(self, requeue: bool = False) -> None:
        pending = not self.acknowledged
        super().reject(requeue=requeue)
        if pending and self.acknowledged:
            drain.settled()


class OneShotTask(Task):
    abstract = True
    Request = "src.oneshot:OneShotRequest"


class OneShotConsumer(bootsteps.StartStopStep):
    requires = {"celery.worker.consumer.tasks:Tasks"}

    def include_if(self, parent: Any) -> bool:
        return os.getenv("SCHOLENS_WORKER_ONE_SHOT") == "1"

    def start(self, consumer: Any) -> None:
        global drain
        if consumer.pool.num_processes != 1 or consumer.initial_prefetch_count != 1:
            raise RuntimeError("One-shot workers require concurrency and prefetch one")
        if len(consumer.task_consumer.queues) != 1:
            raise RuntimeError("One-shot workers require exactly one queue")
        if getattr(self, "started_once", False):
            # A reconnect must not take another message while a prior delivery
            # may still own its durable lease. Let Celery perform warm shutdown.
            consumer.task_consumer.cancel()
            worker_state.should_stop = 0  # type: ignore[attr-defined]
            return
        self.started_once = True
        drain = DrainState(
            started=time.monotonic(),
            max_tasks=int(os.getenv("SCHOLENS_WORKER_MAX_TASKS", "1")),
            max_seconds=float(os.getenv("SCHOLENS_WORKER_MAX_SECONDS", "300")),
        )
        self.consumption_cancelled = False
        self.consumer = consumer
        signals.task_received.connect(self.received, weak=False)  # type: ignore[attr-defined]
        self.timer = consumer.timer.call_repeatedly(1.0, self.check)

    def received(self, sender: Any = None, **_kwargs: Any) -> None:
        if sender is self.consumer:
            drain.received()
            if drain.stop_consuming(now=time.monotonic()):
                self.cancel_consumption()

    def cancel_consumption(self) -> None:
        if not self.consumption_cancelled:
            self.consumer.task_consumer.cancel()
            self.consumption_cancelled = True

    def check(self) -> None:
        now = time.monotonic()
        if drain.stop_consuming(now=now):
            self.cancel_consumption()
        if drain.should_exit(now=now):
            self.cancel_consumption()
            worker_state.should_stop = 0  # type: ignore[attr-defined]

    def stop(self, consumer: Any) -> None:
        self.timer.cancel()
        signals.task_received.disconnect(self.received)  # type: ignore[attr-defined]
