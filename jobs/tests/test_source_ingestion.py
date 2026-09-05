from __future__ import annotations

import hashlib
import json
import logging
import socket

import httpx
import pytest
import requests

from src import tasks


class _PublicPeer:
    def get_extra_info(self, name: str) -> tuple[str, int] | None:
        return ("93.184.216.34", 443) if name == "server_addr" else None


def _client_for(
    *,
    status: int,
    headers: dict[str, str] | None = None,
    content: bytes = b"",
) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers=headers,
            stream=httpx.ByteStream(content),
            request=request,
            extensions={"network_stream": _PublicPeer()},
        )

    return httpx.Client(
        transport=httpx.MockTransport(respond),
        follow_redirects=False,
    )


def _public_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def test_stream_source_without_content_length_hashes_directly_to_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = b"%PDF-1.7\n" + b"x" * 2048 + b"\n%%EOF"
    client = _client_for(
        status=200,
        headers={"content-type": "application/pdf"},
        content=pdf,
    )
    monkeypatch.setattr(tasks.socket, "getaddrinfo", _public_dns)
    monkeypatch.setattr(tasks.httpx, "Client", lambda **_kwargs: client)

    destination = tmp_path / "source.pdf"
    digest, size = tasks._stream_url_to_file(
        "https://example.org/paper.pdf",
        str(destination),
        job_id="job-1",
        attempt=1,
    )

    assert destination.read_bytes() == pdf
    assert size == len(pdf)
    assert digest == hashlib.sha256(pdf).hexdigest()


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(404, False), (429, True), (503, True)],
)
def test_stream_source_classifies_http_failures(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    retryable: bool,
) -> None:
    client = _client_for(
        status=status,
        headers={"retry-after": "7"},
    )
    monkeypatch.setattr(tasks.socket, "getaddrinfo", _public_dns)
    monkeypatch.setattr(tasks.httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(tasks.SourceDownloadError) as raised:
        tasks._stream_url_to_file(
            "https://example.org/paper.pdf",
            str(tmp_path / "source.pdf"),
            job_id="job-1",
            attempt=1,
        )

    assert raised.value.status == status
    assert raised.value.retryable is retryable
    if retryable:
        assert raised.value.retry_after == 7


def test_stream_source_enforces_limit_without_content_length(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client_for(
        status=200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-1.7\n" + b"x" * 2048,
    )
    monkeypatch.setattr(tasks.socket, "getaddrinfo", _public_dns)
    monkeypatch.setattr(tasks.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(tasks, "SOURCE_MAX_BYTES", 1024)

    with pytest.raises(tasks.SourceDownloadError) as raised:
        tasks._stream_url_to_file(
            "https://example.org/paper.pdf",
            str(tmp_path / "source.pdf"),
            job_id="job-1",
            attempt=1,
        )

    assert raised.value.error_code == "upload_too_large"


def _requests_response(
    status: int, payload: dict[str, object], *, retry_after: str | None = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers["content-type"] = "application/json"
    if retry_after is not None:
        response.headers["retry-after"] = retry_after
    response._content = json.dumps(payload).encode()
    return response


def test_provider_source_resolution_returns_validated_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks,
        "post_signed_json",
        lambda *_args, **_kwargs: _requests_response(
            200, {"resolved_url": "https://repository.example/paper.pdf"}
        ),
    )

    assert tasks._resolve_source_url("https://server/internal/source-url") == (
        "https://repository.example/paper.pdf"
    )


@pytest.mark.parametrize(
    ("status", "retryable"), [(422, False), (429, True), (503, True)]
)
def test_provider_source_resolution_preserves_safe_failure_code(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    retryable: bool,
) -> None:
    monkeypatch.setattr(
        tasks,
        "post_signed_json",
        lambda *_args, **_kwargs: _requests_response(
            status,
            {"error": {"code": "openalex_credential_invalid"}},
            retry_after="7",
        ),
    )

    with pytest.raises(tasks.SourceDownloadError) as raised:
        tasks._resolve_source_url("https://server/internal/source-url")

    assert raised.value.error_code == "openalex_credential_invalid"
    assert raised.value.status == status
    assert raised.value.retryable is retryable
    assert raised.value.retry_after == 7


def test_source_temp_cleanup_is_idempotent(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\n%%EOF")

    tasks._cleanup_source_temp(str(source), job_id="job-1")
    with caplog.at_level(logging.WARNING):
        tasks._cleanup_source_temp(str(source), job_id="job-1")

    assert not source.exists()
    assert "job.source_temp.cleanup_failed" not in caplog.messages


def test_source_temp_cleanup_reports_real_os_failures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def deny_cleanup(_path: str) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(tasks.os, "unlink", deny_cleanup)

    with caplog.at_level(logging.WARNING):
        tasks._cleanup_source_temp("/tmp/source.pdf", job_id="job-1")

    assert "job.source_temp.cleanup_failed" in caplog.messages
