from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.sampling import Decision

import scholens_observability.tracing as tracing_module
from scholens_observability import configure_telemetry, instrumented_span


def test_metric_views_drop_duplicate_http_server_metrics_and_keep_custom_red() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        metric_readers=[reader],
        views=tracing_module._metric_views(),
    )
    meter = provider.get_meter("tests")

    dropped_names = {
        "http.server.duration",
        "http.server.request.duration",
        "http.server.request.size",
        "http.server.request.body.size",
        "http.server.response.size",
        "http.server.response.body.size",
        "http.server.active_requests",
    }
    for name in dropped_names - {"http.server.active_requests"}:
        meter.create_histogram(name).record(1)
    active_requests = meter.create_up_down_counter("http.server.active_requests")
    active_requests.add(1)
    meter.create_counter("scholens.http.requests").add(1, {"route": "/health"})
    meter.create_histogram("scholens.http.duration").record(0.01, {"route": "/health"})

    metrics_data = reader.get_metrics_data()
    exported_names = {
        metric.name
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }

    assert dropped_names.isdisjoint(exported_names)
    assert {"scholens.http.requests", "scholens.http.duration"} <= exported_names
    provider.shutdown()


def test_reservoir_sampler_keeps_one_trace_per_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((10.1, 10.8, 11.0))
    monkeypatch.setattr(tracing_module, "monotonic", lambda: next(moments))
    sampler = tracing_module._ReservoirRatioSampler(0)

    first = sampler.should_sample(None, 1, "first")
    remainder = sampler.should_sample(None, 2, "remainder")
    next_second = sampler.should_sample(None, 3, "next-second")

    assert first.decision is Decision.RECORD_AND_SAMPLE
    assert remainder.decision is Decision.DROP
    assert next_second.decision is Decision.RECORD_AND_SAMPLE


def test_disabled_telemetry_is_a_noop_and_spans_remain_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tracing_module, "_CONFIGURED", False)

    configure_telemetry(
        service="tests",
        environment="test",
        release=None,
        endpoint=None,
    )

    assert tracing_module._CONFIGURED is False
    with instrumented_span("test.span", attributes={"component": "tests"}) as span:
        assert span is trace.get_current_span()
