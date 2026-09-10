"""A one-shot worker must finish broker settlement before exiting."""

from unittest.mock import Mock

from src.oneshot import DrainState, OneShotRequest


def test_received_work_prevents_idle_exit_until_broker_settles() -> None:
    state = DrainState(started=0)
    state.received()
    assert not state.should_exit(now=90)
    state.settled()
    assert state.should_exit(now=91)


def test_empty_worker_exits_after_bounded_wait() -> None:
    state = DrainState(started=0)
    assert not state.should_exit(now=29)
    assert state.should_exit(now=30)


def test_ack_failure_does_not_mark_request_settled(monkeypatch) -> None:
    from src import oneshot

    state = DrainState(started=0)
    state.received()
    monkeypatch.setattr(oneshot, "drain", state)
    request = object.__new__(OneShotRequest)
    request.acknowledged = False
    request._connection_errors = ()
    request._on_ack = Mock(side_effect=RuntimeError("broker unavailable"))
    try:
        request.acknowledge()
    except RuntimeError:
        pass
    assert not state.should_exit(now=90)


def test_successful_ack_and_requeue_both_release_worker(monkeypatch) -> None:
    from src import oneshot

    for requeue in (False, True):
        state = DrainState(started=0)
        state.received()
        monkeypatch.setattr(oneshot, "drain", state)
        request = object.__new__(OneShotRequest)
        request.acknowledged = False
        request._connection_errors = ()
        request._on_ack = Mock()
        request._on_reject = Mock()
        monkeypatch.setattr(OneShotRequest, "send_event", Mock())
        if requeue:
            request.reject(requeue=True)
        else:
            request.acknowledge()
        assert state.should_exit(now=1)
