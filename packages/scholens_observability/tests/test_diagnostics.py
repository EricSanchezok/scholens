from __future__ import annotations

import gzip
import json
import logging
from uuid import UUID

import pytest

from scholens_observability import (
    BufferedS3DiagnosticSnapshotRecorder,
    SensitiveValue,
    build_snapshot,
    should_sample_success,
)


def _snapshot(*, sections: dict[str, object]):
    return build_snapshot(
        snapshot_id=UUID(int=1),
        service="api",
        environment="test",
        release="revision-1",
        reason="test",
        request_id="request-1",
        operation_id="operation-1",
        correlation_id="correlation-1",
        actor_id="actor-1",
        sections=sections,
    )


@pytest.mark.parametrize(
    "sections",
    [
        {"request": {"api_key": "secret"}},
        {"request": {"value": SensitiveValue("secret")}},
        {"request": {"note": "authorization=Bearer secret-value"}},
        {"request": {"token": "a" * 20 + "." + "b" * 20 + "." + "c" * 20}},
    ],
)
def test_snapshot_rejects_sensitive_keys_and_values(
    sections: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _snapshot(sections=sections)


def test_snapshot_accepts_json_data_and_sampling_is_deterministic() -> None:
    snapshot = _snapshot(
        sections={"failure": {"code": "provider_timeout", "attempt": 2}}
    )

    assert snapshot.sections == {"failure": {"code": "provider_timeout", "attempt": 2}}
    assert snapshot.truncated is False
    assert should_sample_success("stable-id", rate=0) is False
    assert should_sample_success("stable-id", rate=1) is True
    with pytest.raises(ValueError, match="between zero and one"):
        should_sample_success("stable-id", rate=1.01)


def test_buffered_snapshot_writer_encrypts_and_compresses_payload() -> None:
    class FakeObjectStorage:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def put_object(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            return {}

    client = FakeObjectStorage()
    recorder = BufferedS3DiagnosticSnapshotRecorder(
        client=client,
        bucket="diagnostics",
        kms_key_id="alias/scholens-diagnostics",
        prefix="api",
    )
    snapshot = _snapshot(sections={"failure": {"code": "test"}})
    recorder.record(snapshot)
    recorder.close()

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Key"] == (
        f"api/{snapshot.captured_at:%Y/%m/%d}/correlation-1/api/{snapshot.id}.json.gz"
    )
    assert call["ServerSideEncryption"] == "aws:kms"
    assert call["SSEKMSKeyId"] == "alias/scholens-diagnostics"
    body = call["Body"]
    assert isinstance(body, bytes)
    payload = json.loads(gzip.decompress(body))
    assert payload["sections"] == {"failure": {"code": "test"}}


def test_buffered_snapshot_writer_logs_safe_origin_context_on_aws_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class StorageFailure(Exception):
        operation_name = "PutObject"
        response = {
            "Error": {
                "Code": "AccessDenied",
                "Message": "do not log diagnostics/private-object",
            },
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }

    class FailingObjectStorage:
        def put_object(self, **_kwargs: object) -> object:
            raise StorageFailure("do not log diagnostics/private-object")

    recorder = BufferedS3DiagnosticSnapshotRecorder(
        client=FailingObjectStorage(),
        bucket="diagnostics",
        kms_key_id="alias/scholens-diagnostics",
        prefix="api",
    )
    with caplog.at_level(logging.ERROR):
        recorder.record(_snapshot(sections={"failure": {"code": "test"}}))
        recorder.close()

    record = next(
        item
        for item in caplog.records
        if item.getMessage() == "diagnostic.snapshot.write_failed"
    )
    assert getattr(record, "diagnostic_service") == "api"
    assert getattr(record, "diagnostic_environment") == "test"
    assert getattr(record, "diagnostic_release") == "revision-1"
    assert getattr(record, "request_id") == "request-1"
    assert getattr(record, "operation_id") == "operation-1"
    assert getattr(record, "correlation_id") == "correlation-1"
    assert getattr(record, "aws_error_code") == "AccessDenied"
    assert getattr(record, "aws_operation") == "PutObject"
    assert getattr(record, "aws_http_status") == 403
    assert "private-object" not in caplog.text


def test_buffered_snapshot_writer_drops_before_exceeding_memory_budget() -> None:
    class FakeObjectStorage:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def put_object(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            return {}

    client = FakeObjectStorage()
    recorder = BufferedS3DiagnosticSnapshotRecorder(
        client=client,
        bucket="diagnostics",
        kms_key_id="alias/scholens-diagnostics",
        max_buffered_bytes=1,
    )
    recorder.record(_snapshot(sections={"failure": {"code": "test"}}))
    recorder.close()

    assert client.calls == []
