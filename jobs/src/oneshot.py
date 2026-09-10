"""Optional single-delivery Celery lifecycle for admitted ECS RunTask workers."""

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
    received_count: int = 0
    settled_count: int = 0

    def received(self) -> None:
        self.received_count += 1

    def settled(self) -> None:
        self.settled_count += 1

    def should_exit(self, *, now: float) -> bool:
        if self.settled_count and self.settled_count >= self.received_count:
            return True
        return not self.received_count and now - self.started >= 30


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
        drain = DrainState(started=time.monotonic())
        self.consumer = consumer
        signals.task_received.connect(self.received, weak=False)  # type: ignore[attr-defined]
        self.timer = consumer.timer.call_repeatedly(1.0, self.check)

    def received(self, sender: Any = None, **_kwargs: Any) -> None:
        if sender is self.consumer:
            drain.received()
            # Do not reserve a second message after acknowledging the first.
            self.consumer.task_consumer.cancel()

    def check(self) -> None:
        if drain.should_exit(now=time.monotonic()):
            worker_state.should_stop = 0  # type: ignore[attr-defined]

    def stop(self, consumer: Any) -> None:
        self.timer.cancel()
        signals.task_received.disconnect(self.received)  # type: ignore[attr-defined]
