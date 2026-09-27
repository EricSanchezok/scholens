from __future__ import annotations

import src.observability as observability


def test_failure_signal_preserves_duration_until_postrun(monkeypatch) -> None:
    from types import SimpleNamespace

    events = []
    monkeypatch.setattr(observability, "_TASK_STARTS", {"failed-job": 10.0})
    monkeypatch.setattr(observability, "monotonic", lambda: 12.5)
    monkeypatch.setattr(observability, "_record_task_snapshot", lambda **_: None)
    monkeypatch.setattr(
        observability,
        "log_event",
        lambda _logger, _level, event, **fields: events.append((event, fields)),
    )
    task = SimpleNamespace(name="postprocess_pdf")
    observability._task_failure(task_id="failed-job", sender=task)
    observability._task_postrun(task_id="failed-job", task=task, state="FAILURE")
    assert events[-1][1]["duration_ms"] == 2500.0
    assert "failed-job" not in observability._TASK_STARTS


def test_jobs_diagnostic_recorder_uses_iam_scoped_prefix(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Recorder:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def record(self, snapshot: object) -> None:
            del snapshot

    monkeypatch.setenv("DIAGNOSTIC_SNAPSHOT_BUCKET", "diagnostics")
    monkeypatch.setenv(
        "DIAGNOSTIC_SNAPSHOT_KMS_KEY_ID",
        "alias/scholens-diagnostics",
    )
    monkeypatch.setattr(observability, "_CONFIGURED", False)
    monkeypatch.setattr(observability, "_OTLP_ENDPOINT", None)
    monkeypatch.setattr(observability, "configure_logging", lambda **_kwargs: None)
    monkeypatch.setattr(observability, "configure_telemetry", lambda **_kwargs: None)
    monkeypatch.setattr(observability, "_connect_task_signals", lambda: None)
    monkeypatch.setattr(
        observability,
        "BufferedS3DiagnosticSnapshotRecorder",
        Recorder,
    )
    monkeypatch.setattr(observability.boto3, "client", lambda _service: object())

    observability.configure_jobs_observability()

    assert captured["prefix"] == "workers"
