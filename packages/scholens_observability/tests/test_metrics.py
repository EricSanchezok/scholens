from __future__ import annotations

import logging

import pytest

import scholens_observability.metrics as metrics_module
from scholens_observability import add_counter, record_histogram


def test_metric_helpers_forward_values_and_copy_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int | float, dict[str, object]]] = []

    class FakeCounter:
        def add(self, value: int, *, attributes: dict[str, object]) -> None:
            calls.append(("counter", value, attributes))

    class FakeHistogram:
        def record(
            self,
            value: int | float,
            *,
            attributes: dict[str, object],
        ) -> None:
            calls.append(("histogram", value, attributes))

    class FakeMeter:
        def create_counter(self, _name: str) -> FakeCounter:
            return FakeCounter()

        def create_histogram(self, _name: str, *, unit: str) -> FakeHistogram:
            assert unit == "ms"
            return FakeHistogram()

    metrics_module._counter.cache_clear()
    metrics_module._histogram.cache_clear()
    monkeypatch.setattr(metrics_module.metrics, "get_meter", lambda _name: FakeMeter())

    attributes = {"operation": "parse"}
    add_counter("jobs.started", 2, attributes=attributes)
    record_histogram("jobs.duration", 12.5, attributes=attributes)

    assert calls == [
        ("counter", 2, {"operation": "parse"}),
        ("histogram", 12.5, {"operation": "parse"}),
    ]


def test_metric_delivery_failure_never_changes_product_control_flow(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenCounter:
        def add(self, _value: int, *, attributes: dict[str, object]) -> None:
            assert attributes == {}
            raise RuntimeError("collector unavailable")

    class FakeMeter:
        def create_counter(self, _name: str) -> BrokenCounter:
            return BrokenCounter()

    metrics_module._counter.cache_clear()
    monkeypatch.setattr(metrics_module.metrics, "get_meter", lambda _name: FakeMeter())

    with caplog.at_level(logging.WARNING):
        add_counter("jobs.failed")

    assert "observability.metric.counter_failed" in caplog.text
