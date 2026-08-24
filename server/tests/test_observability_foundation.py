from __future__ import annotations

import json
import logging
import gzip
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.utils import is_instrumentation_enabled
from scholens_observability import (
    ObservabilityContext,
    BufferedS3DiagnosticSnapshotRecorder,
    SensitiveValue,
    bind_context,
    build_snapshot,
    configure_logging,
    current_context,
    diagnostic_id,
    log_event,
    set_context,
    should_sample_success,
)

from app.bootstrap.settings import AppSettings
from app.observability import diagnostics as diagnostic_composition
from app.observability.runtime import _fastapi_request_hook
from app.shared.application import Actor, OperationContextFactory
from app.transport.http import observability as http_observability
from app.transport.http.observability import (
    RequestObservabilityMiddleware,
    is_reading_activity_request,
    safe_http_route_template,
)
from app.transport.http.public_v1.auth_dependencies import (
    resolve_actor_from_identity_user,
)


def test_context_is_scoped_and_restored() -> None:
    set_context(ObservabilityContext(service="test", environment="test"))
    with bind_context(request_id="request-1", component="chat"):
        assert current_context().request_id == "request-1"
        assert current_context().component == "chat"
    assert current_context().request_id is None
    assert current_context().component is None


def test_structured_logging_drops_security_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class SecretRepr:
        def __str__(self) -> str:
            return "embedded-password-must-not-appear"

    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        configure_logging(service="test", environment="production")
        logger = logging.getLogger("tests.observability")
        log_event(
            logger,
            logging.ERROR,
            "test.failure",
            api_key="must-not-appear",
            safe_identifier="visible",
            unsafe_object=SecretRepr(),
            exc_info=RuntimeError("postgres://user:secret@example.invalid/db"),
        )
        output = capsys.readouterr().out.strip()
        payload = json.loads(output)
        assert payload["event"] == "test.failure"
        assert payload["safe_identifier"] == "visible"
        assert payload["exception_type"] == "RuntimeError"
        assert payload["unsafe_object"] == "<SecretRepr>"
        assert "must-not-appear" not in output
        assert "embedded-password" not in output
        assert "postgres://" not in output
    finally:
        root.handlers.clear()
        root.handlers.extend(previous_handlers)
        root.setLevel(previous_level)


def test_structured_logging_redacts_inline_credentials(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        configure_logging(service="test", environment="production")
        logging.getLogger("tests.observability").error(
            "dependency.failed authorization=Bearer abcdefghijklmnopqrstuvwxyz"
        )
        output = capsys.readouterr().out.strip()
        assert "abcdefghijklmnopqrstuvwxyz" not in output
        assert "[REDACTED]" in output
    finally:
        root.handlers.clear()
        root.handlers.extend(previous_handlers)
        root.setLevel(previous_level)


def test_diagnostic_snapshot_rejects_credentials() -> None:
    with pytest.raises(ValueError, match="Security-sensitive"):
        build_snapshot(
            snapshot_id=diagnostic_id(),
            service="api",
            environment="test",
            release=None,
            reason="test",
            request_id=None,
            operation_id=None,
            correlation_id=None,
            actor_id=None,
            sections={"request": {"connector_api_key": "secret"}},
        )
    with pytest.raises(ValueError, match="Sensitive value"):
        build_snapshot(
            snapshot_id=diagnostic_id(),
            service="api",
            environment="test",
            release=None,
            reason="test",
            request_id=None,
            operation_id=None,
            correlation_id=None,
            actor_id=None,
            sections={"request": {"value": SensitiveValue("secret")}},
        )
    with pytest.raises(ValueError, match="Security-sensitive diagnostic value"):
        build_snapshot(
            snapshot_id=diagnostic_id(),
            service="api",
            environment="test",
            release=None,
            reason="test",
            request_id=None,
            operation_id=None,
            correlation_id=None,
            actor_id=None,
            sections={"request": {"note": "api_key=connector-secret-value"}},
        )


def test_success_sampling_is_deterministic() -> None:
    correlation_id = uuid4()
    values = {should_sample_success(correlation_id, rate=0.5) for _ in range(10)}
    assert len(values) == 1


def test_buffered_snapshot_recorder_writes_encrypted_gzip() -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def put_object(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            return {}

    client = FakeS3()
    recorder = BufferedS3DiagnosticSnapshotRecorder(
        client=client,
        bucket="diagnostics",
        kms_key_id="alias/scholens-diagnostics",
    )
    snapshot = build_snapshot(
        snapshot_id=diagnostic_id(),
        service="api",
        environment="test",
        release="abc123",
        reason="test_failure",
        request_id="request-1",
        operation_id=None,
        correlation_id="correlation-1",
        actor_id="42",
        sections={"failure": {"code": "test_failure"}},
    )
    recorder.record(snapshot)
    deadline = time.monotonic() + 1
    while not client.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    recorder.close()

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["ServerSideEncryption"] == "aws:kms"
    assert call["SSEKMSKeyId"] == "alias/scholens-diagnostics"
    body = call["Body"]
    assert isinstance(body, bytes)
    payload = json.loads(gzip.decompress(body))
    assert payload["reason"] == "test_failure"
    assert payload["sections"]["failure"]["code"] == "test_failure"


def test_api_diagnostic_recorder_uses_iam_scoped_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Recorder:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def record(self, snapshot: object) -> None:
            del snapshot

    monkeypatch.setattr(
        diagnostic_composition,
        "BufferedS3DiagnosticSnapshotRecorder",
        Recorder,
    )
    monkeypatch.setattr(
        diagnostic_composition.boto3,
        "client",
        lambda _service: object(),
    )

    diagnostic_composition.create_diagnostic_snapshot_recorder(
        AppSettings(
            diagnostic_snapshot_bucket="diagnostics",
            diagnostic_snapshot_kms_key_id="alias/scholens-diagnostics",
        )
    )

    assert captured["prefix"] == "api"


def test_snapshot_recorder_drops_work_before_exceeding_memory_budget() -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def put_object(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            return {}

    client = FakeS3()
    recorder = BufferedS3DiagnosticSnapshotRecorder(
        client=client,
        bucket="diagnostics",
        kms_key_id="alias/scholens-diagnostics",
        max_buffered_bytes=1,
    )
    recorder.record(
        build_snapshot(
            snapshot_id=diagnostic_id(),
            service="api",
            environment="test",
            release=None,
            reason="oversized_for_queue",
            request_id="request-1",
            operation_id=None,
            correlation_id="correlation-1",
            actor_id="42",
            sections={"failure": {"code": "test_failure"}},
        )
    )
    recorder.close()

    assert client.calls == []


def test_request_middleware_assigns_trusted_request_id() -> None:
    app = FastAPI()
    app.add_middleware(
        RequestObservabilityMiddleware,
        service="test-api",
        environment="test",
        release=None,
    )

    @app.get("/items/{item_id}")
    def item(item_id: str, request: Request) -> dict[str, str]:
        request.state.correlation_id = str(UUID(int=1))
        return {"item_id": item_id, "request_id": request.state.request_id}

    with TestClient(app) as client:
        response = client.get(
            "/items/example",
            headers={"X-Request-ID": str(UUID(int=2))},
        )

    assert response.status_code == 200
    response_id = response.headers["X-Request-ID"]
    UUID(response_id)
    assert response_id != str(UUID(int=2))
    assert response.json()["request_id"] == response_id
    assert response.headers["X-Correlation-ID"] == str(UUID(int=1))


def test_success_snapshots_skip_reads_and_sample_authenticated_commands() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.snapshots: list[object] = []

        def record(self, snapshot: object) -> None:
            self.snapshots.append(snapshot)

    recorder = Recorder()
    app = FastAPI()
    app.state.diagnostic_snapshot_recorder = recorder
    app.add_middleware(
        RequestObservabilityMiddleware,
        service="test-api",
        environment="test",
        release=None,
        success_sample_rate=1,
    )

    @app.api_route("/items", methods=["GET", "POST"])
    def items(request: Request) -> dict[str, bool]:
        request.state.authenticated = True
        request.state.correlation_id = str(UUID(int=3))
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/items").status_code == 200
        assert recorder.snapshots == []
        assert client.post("/items").status_code == 200

    assert len(recorder.snapshots) == 1


def test_reading_activity_span_replaces_all_resource_ids_and_actor_facts() -> None:
    class Span:
        def __init__(self) -> None:
            self.attributes: dict[str, object] = {}
            self.name = ""

        def set_attribute(self, key: str, value: object) -> None:
            self.attributes[key] = value

        def update_name(self, value: str) -> None:
            self.name = value

    app = FastAPI()

    @app.put("/api/v1/reading-sessions/{session_id}")
    def heartbeat(session_id: UUID) -> None:
        del session_id

    @app.post("/api/v1/papers/{document_id}/reading-sessions")
    def start(document_id: UUID) -> None:
        del document_id

    @app.get("/api/v1/projects/{project_id}/insights")
    def insights(project_id: UUID) -> None:
        del project_id

    @app.get("/api/v1/health")
    def health() -> None:
        return None

    secret = "private-query-token"
    for method, path, expected_route in (
        (
            "PUT",
            f"/api/v1/reading-sessions/{uuid4()}",
            "/api/v1/reading-sessions/{session_id}",
        ),
        (
            "POST",
            f"/api/v1/papers/{uuid4()}/reading-sessions",
            "/api/v1/papers/{document_id}/reading-sessions",
        ),
        (
            "GET",
            f"/api/v1/projects/{uuid4()}/insights",
            "/api/v1/projects/{project_id}/insights",
        ),
        ("GET", "/api/v1/health", "/api/v1/health"),
    ):
        span = Span()
        raw_url = f"https://api.example.test{path}?token={secret}"
        span.attributes.update(
            {
                "http.target": f"{path}?token={secret}",
                "http.url": raw_url,
                "url.full": raw_url,
                "url.path": path,
                "url.query": f"token={secret}",
            }
        )
        _fastapi_request_hook(
            span,
            {
                "type": "http",
                "app": app,
                "method": method,
                "path": path,
                "root_path": "",
                "scheme": "https",
                "server": ("api.example.test", 443),
                "query_string": f"token={secret}".encode(),
                "headers": [],
            },
        )

        rendered = f"{span.name} {span.attributes}"
        assert secret not in rendered
        assert span.attributes["http.route"] == expected_route
        assert span.attributes["http.target"] == expected_route
        assert span.attributes["url.path"] == expected_route
        assert span.attributes["url.query"] == ""
        assert "?" not in str(span.attributes["url.full"])
        if "{" in expected_route:
            assert path not in rendered
            resource_ids = [part for part in path.split("/") if _is_uuid(part)]
            assert not any(resource_id in rendered for resource_id in resource_ids)
        if method in {"POST", "PUT"}:
            assert span.attributes["client.address"] == ""
            assert span.attributes["enduser.id"] == ""


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def test_reading_activity_auth_does_not_attach_actor_diagnostic_context() -> None:
    actor = Actor(
        id=41,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )
    executor = MagicMock()
    executor.command.return_value = actor
    scope = {
        "type": "http",
        "method": "PUT",
        "path": f"/api/v1/reading-sessions/{uuid4()}",
        "route": SimpleNamespace(path="/api/v1/reading-sessions/{session_id}"),
        "headers": [],
        "query_string": b"",
        "state": {},
    }
    request = Request(scope)

    resolved = resolve_actor_from_identity_user(
        request=request,
        identity_user=SimpleNamespace(
            id=41,
            email="reader@example.com",
            display_name="Reader",
            status="active",
            email_verified=True,
        ),
        executor=executor,
        operation_factory=OperationContextFactory(),
    )

    assert resolved == actor
    assert request.state.authenticated is True
    assert not hasattr(request.state, "actor_id")
    assert request.state.operation_context is not None
    assert not hasattr(request.state, "operation_id")
    assert not hasattr(request.state, "correlation_id")


@pytest.mark.parametrize(
    ("method", "path", "expected_route"),
    [
        (
            "PUT",
            "/api/v1/reading-sessions/not-a-uuid",
            "/api/v1/reading-sessions/{session_id}",
        ),
        (
            "DELETE",
            "/api/v1/reading-sessions/not-a-uuid/",
            "/api/v1/reading-sessions/{session_id}",
        ),
        (
            "POST",
            "/api/v1/papers/not-a-uuid/reading-sessions/",
            "/api/v1/papers/{document_id}/reading-sessions",
        ),
        (
            "GET",
            "/api/v1/papers/not-a-uuid/insights/",
            "/api/v1/papers/{document_id}/insights",
        ),
        (
            "GET",
            "/api/v1/projects/not-a-uuid/activity/",
            "/api/v1/projects/{project_id}/activity",
        ),
        (
            "GET",
            "/api/v1/me/reading-activity-preferences/",
            "/api/v1/me/reading-activity-preferences",
        ),
        (
            "GET",
            "/api/v1/me/reading-activity/export/",
            "/api/v1/me/reading-activity/export",
        ),
    ],
)
def test_reading_activity_pre_route_fallback_is_private_and_low_cardinality(
    method: str,
    path: str,
    expected_route: str,
) -> None:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "state": {},
    }

    assert "route" not in scope
    assert is_reading_activity_request(scope) is True
    assert safe_http_route_template(scope) == expected_route
    assert "not-a-uuid" not in safe_http_route_template(scope)


def test_reading_activity_pre_route_matcher_follows_fastapi_case_sensitivity() -> None:
    scope = {
        "type": "http",
        "method": "PUT",
        "path": "/API/v1/reading-sessions/not-a-uuid",
        "headers": [],
        "query_string": b"",
        "state": {},
    }

    assert is_reading_activity_request(scope) is False
    assert safe_http_route_template(scope) == scope["path"]


def test_reading_activity_requests_emit_metrics_without_logs_or_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = MagicMock()
    app = FastAPI()
    app.state.diagnostic_snapshot_recorder = recorder
    app.add_middleware(
        RequestObservabilityMiddleware,
        service="test-api",
        environment="test",
        release=None,
        success_sample_rate=1,
    )

    @app.put("/api/v1/reading-sessions/{session_id}")
    def heartbeat(session_id: UUID, request: Request) -> dict[str, bool]:
        del session_id
        request.state.authenticated = True
        request.state.actor_id = "41"
        request.state.correlation_id = str(uuid4())
        return {"ok": True, "instrumentation_enabled": is_instrumentation_enabled()}

    @app.post("/api/v1/papers/{document_id}/reading-sessions")
    def start(document_id: UUID) -> dict[str, bool]:
        del document_id
        return {"instrumentation_enabled": is_instrumentation_enabled()}

    @app.get("/api/v1/projects/{project_id}/insights")
    def project_insights(project_id: UUID) -> dict[str, bool]:
        del project_id
        return {"instrumentation_enabled": is_instrumentation_enabled()}

    @app.get("/normal")
    def normal() -> dict[str, bool]:
        return {"instrumentation_enabled": is_instrumentation_enabled()}

    logged = MagicMock()
    counters = MagicMock()
    monkeypatch.setattr(http_observability, "log_event", logged)
    monkeypatch.setattr(http_observability, "add_counter", counters)
    with TestClient(app) as client:
        response = client.put(f"/api/v1/reading-sessions/{uuid4()}")
        assert response.status_code == 200
        assert response.json()["instrumentation_enabled"] is False
        logged.assert_not_called()
        recorder.record.assert_not_called()

        # Classification happens before FastAPI has attached the route. A
        # malformed resource identifier must still stay inside the private
        # telemetry boundary while request validation returns 422.
        for method, path in (
            ("PUT", "/api/v1/reading-sessions/not-a-uuid"),
            ("PUT", "/api/v1/reading-sessions/not-a-uuid/"),
            ("POST", "/api/v1/papers/not-a-uuid/reading-sessions/"),
            ("GET", "/api/v1/projects/not-a-uuid/insights/"),
        ):
            malformed = client.request(method, path)
            assert malformed.status_code == 422
            logged.assert_not_called()
            recorder.record.assert_not_called()

        trailing = client.put(f"/api/v1/reading-sessions/{uuid4()}/")
        assert trailing.status_code == 200
        assert trailing.json()["instrumentation_enabled"] is False
        logged.assert_not_called()
        recorder.record.assert_not_called()

        metric_calls = str(counters.call_args_list)
        assert "not-a-uuid" not in metric_calls
        assert "/api/v1/reading-sessions/{session_id}" in metric_calls
        assert "/api/v1/papers/{document_id}/reading-sessions" in metric_calls
        assert "/api/v1/projects/{project_id}/insights" in metric_calls

        normal_response = client.get("/normal")

    assert normal_response.json()["instrumentation_enabled"] is True
    assert logged.call_count == 2
