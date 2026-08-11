from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from app.helpers.parser import (
    _validate_public_http_url,
    validate_pdf_content,
    validate_url_and_fetch_pdf,
)
from pypdf import PdfWriter


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/paper.pdf",
        "https://user:password@example.com/paper.pdf",
    ],
)
def test_pdf_url_rejects_unsupported_or_credentialed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_public_http_url(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "fe80::1",
    ],
)
def test_pdf_url_rejects_non_public_dns_answers(address: str) -> None:
    family = 10 if ":" in address else 2
    with (
        patch(
            "app.helpers.parser.socket.getaddrinfo",
            return_value=[(family, 1, 6, "", (address, 443))],
        ),
        pytest.raises(ValueError, match="public"),
    ):
        _validate_public_http_url("https://example.com/paper.pdf")


def test_pdf_url_accepts_only_when_all_dns_answers_are_public() -> None:
    answers = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
    ]
    with patch("app.helpers.parser.socket.getaddrinfo", return_value=answers):
        _validate_public_http_url("https://example.com/paper.pdf")


def test_structurally_valid_scanned_pdf_reaches_jobs_ocr_pipeline() -> None:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Description": "scan" * 400})
    writer.write(output)

    valid, error = validate_pdf_content(output.getvalue(), source="test")

    assert valid is True
    assert error == ""


class _NetworkStream:
    def __init__(self, address: str = "93.184.216.34") -> None:
        self.address = address

    def get_extra_info(self, _name: str) -> tuple[str, int]:
        return (self.address, 443)


class _StreamingResponse:
    def __init__(
        self,
        *,
        body: bytes = b"",
        content_type: str = "application/pdf",
        location: str | None = None,
        peer: str = "93.184.216.34",
        status_code: int = 200,
    ) -> None:
        self.body = body
        self.headers = {"content-type": content_type}
        if location is not None:
            self.headers["location"] = location
        self.extensions = {"network_stream": _NetworkStream(peer)}
        self.status_code = status_code
        self.is_redirect = 300 <= status_code < 400

    def __enter__(self) -> _StreamingResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_raw(self, *, chunk_size: int) -> list[bytes]:
        return [
            self.body[index : index + chunk_size]
            for index in range(0, len(self.body), chunk_size)
        ]


class _StreamingClient:
    def __init__(self, responses: list[_StreamingResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def __enter__(self) -> _StreamingClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def stream(self, _method: str, url: str, **_kwargs: object) -> _StreamingResponse:
        self.urls.append(url)
        return self.responses.pop(0)


def _valid_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Description": "paper" * 500})
    writer.write(output)
    return output.getvalue()


def test_pdf_url_revalidates_each_redirect_and_accepts_public_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _StreamingClient(
        [
            _StreamingResponse(status_code=302, location="/download/paper.pdf"),
            _StreamingResponse(body=_valid_pdf()),
        ]
    )
    validate = MagicMock()
    monkeypatch.setattr("app.helpers.parser.httpx.Client", lambda **_kwargs: client)
    monkeypatch.setattr("app.helpers.parser._validate_public_http_url", validate)

    valid, content, error = validate_url_and_fetch_pdf(
        "https://papers.example/start"
    )

    assert valid is True
    assert content.startswith(b"%PDF-")
    assert error == ""
    assert client.urls == [
        "https://papers.example/start",
        "https://papers.example/download/paper.pdf",
    ]
    assert validate.call_count == 2


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            _StreamingResponse(body=b"<html>not a pdf</html>", content_type="text/html"),
            "content type",
        ),
        (
            _StreamingResponse(body=b"not a real pdf" * 100),
            "valid PDF",
        ),
        (
            _StreamingResponse(body=_valid_pdf(), peer="127.0.0.1"),
            "non-public",
        ),
    ],
)
def test_pdf_url_rejects_html_corrupt_content_and_private_peer(
    monkeypatch: pytest.MonkeyPatch,
    response: _StreamingResponse,
    expected: str,
) -> None:
    client = _StreamingClient([response])
    monkeypatch.setattr("app.helpers.parser.httpx.Client", lambda **_kwargs: client)
    monkeypatch.setattr(
        "app.helpers.parser._validate_public_http_url", lambda _url: None
    )

    valid, content, error = validate_url_and_fetch_pdf(
        "https://papers.example/paper.pdf"
    )

    assert valid is False
    assert content == b""
    assert expected in error


def test_pdf_url_blocks_private_redirect_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _StreamingClient(
        [_StreamingResponse(status_code=302, location="http://127.0.0.1/paper.pdf")]
    )
    validate = MagicMock(side_effect=[None, ValueError("non-public redirect")])
    monkeypatch.setattr("app.helpers.parser.httpx.Client", lambda **_kwargs: client)
    monkeypatch.setattr("app.helpers.parser._validate_public_http_url", validate)

    valid, content, error = validate_url_and_fetch_pdf(
        "https://papers.example/redirect"
    )

    assert valid is False
    assert content == b""
    assert error == "non-public redirect"
