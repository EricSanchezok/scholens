from __future__ import annotations

import hashlib
import socket

import httpx
import pytest

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
