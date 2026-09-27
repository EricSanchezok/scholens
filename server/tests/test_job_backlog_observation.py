import asyncio
import logging
import threading

import pytest

from app.modules.jobs.infrastructure import dispatcher


@pytest.mark.asyncio
async def test_backlog_observation_is_periodic_and_off_the_event_loop(monkeypatch):
    stop = asyncio.Event()
    observations = []
    calls = []
    caller = threading.get_ident()
    ticks = iter((0.0, 20.0, 61.0))
    monkeypatch.setattr(dispatcher, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        dispatcher, "dispatch_pending_jobs_once", lambda **_: calls.append(1) or 0
    )
    monkeypatch.setattr(
        dispatcher,
        "observe_pending_backlog",
        lambda: observations.append(threading.get_ident()),
    )

    class Wakeup:
        async def wait(self, _stop, *, timeout):
            if len(calls) == 3:
                stop.set()

    await dispatcher.run_job_dispatcher(stop, wakeup=Wakeup())
    assert len(calls) == 3
    assert len(observations) == 2
    assert all(thread != caller for thread in observations)


def test_failed_backlog_read_cannot_publish_a_healthy_zero(monkeypatch, caplog):
    from app.modules.jobs.infrastructure import backlog_observation as backlog

    def broken_session():
        raise RuntimeError("private database URL must not reach logs")

    monkeypatch.setattr(backlog, "SessionLocal", broken_session)
    with caplog.at_level(logging.INFO):
        backlog.observe_pending_backlog()
    assert [record.message for record in caplog.records] == [
        "jobs.outbox.backlog_observation_failed"
    ]
    assert caplog.records[0].exception_type == "RuntimeError"
    assert "private database URL" not in caplog.text
