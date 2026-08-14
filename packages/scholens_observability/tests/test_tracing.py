from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.sampling import Decision

import scholens_observability.tracing as tracing_module
from scholens_observability import configure_telemetry, instrumented_span


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
