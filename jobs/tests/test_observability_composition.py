from __future__ import annotations

import src.observability as observability


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
