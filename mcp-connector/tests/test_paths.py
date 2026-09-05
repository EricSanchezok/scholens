import hashlib
import json
from pathlib import Path

import httpx
import pytest
from mcp import types
from mcp.shared.exceptions import McpError

from scholens_mcp_connector.cli import (
    MAX_PDF_BYTES,
    MAX_TOOL_WAIT_SECONDS,
    LocalUploadError,
    _local_upload_error_result,
    _local_upload_tool,
    _remote_ingestion_error_with_retry,
    _remote_tool_timeout,
    local_tool_surface,
    resolve_local_pdf,
    upload_local_paper,
    validate_remote_url,
    validate_upload_url,
)


def test_remote_timeout_covers_the_maximum_tool_wait() -> None:
    timeout = _remote_tool_timeout()
    assert timeout.connect == 10
    assert timeout.read is not None
    assert timeout.read >= MAX_TOOL_WAIT_SECONDS + 30


def _pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\n%%EOF")
    return path


def test_resolves_relative_pdf_under_exactly_one_root(tmp_path: Path) -> None:
    paper = _pdf(tmp_path / "paper.pdf")
    assert resolve_local_pdf("paper.pdf", [tmp_path]) == paper


def test_rejects_path_outside_exposed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    paper = _pdf(tmp_path / "paper.pdf")
    with pytest.raises(LocalUploadError, match="outside"):
        resolve_local_pdf(str(paper), [allowed])


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = _pdf(tmp_path / "outside.pdf")
    (allowed / "paper.pdf").symlink_to(outside)
    with pytest.raises(LocalUploadError, match="outside"):
        resolve_local_pdf("paper.pdf", [allowed])


def test_rejects_non_pdf_signature(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"not a pdf")
    with pytest.raises(LocalUploadError, match="signature"):
        resolve_local_pdf(str(paper), [tmp_path])


def test_rejects_oversized_pdf_with_actionable_recovery(tmp_path: Path) -> None:
    paper = tmp_path / "oversized.pdf"
    with paper.open("wb") as stream:
        stream.truncate(MAX_PDF_BYTES + 1)

    with pytest.raises(LocalUploadError) as raised:
        resolve_local_pdf(str(paper), [tmp_path])

    error = raised.value
    assert error.code == "local_pdf_too_large"
    assert error.details == {
        "actual_bytes": MAX_PDF_BYTES + 1,
        "max_bytes": MAX_PDF_BYTES,
    }
    result = _local_upload_error_result(error)
    payload = json.loads(result.content[0].text)["error"]
    assert str(paper) not in json.dumps(payload)
    assert payload == {
        "code": "local_pdf_too_large",
        "details": {
            "actual_bytes": MAX_PDF_BYTES + 1,
            "max_bytes": MAX_PDF_BYTES,
        },
        "message": "The selected PDF exceeds the 30 MiB upload limit",
        "remediation": (
            "Compress or optimize a copy of the PDF to 30 MiB or less, preserve the "
            "original file and text readability, then call "
            "Scholens:upload_local_paper with the compressed copy. Do not retry the "
            "unchanged file."
        ),
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://scholens.example/mcp",
        "http://localhost:7301/mcp",
        "http://127.0.0.1:7301/mcp",
        "http://[::1]:7301/mcp",
    ],
)
def test_remote_url_requires_https_except_for_loopback(url: str) -> None:
    assert validate_remote_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://scholens.example/mcp",
        "https://token@scholens.example/mcp",
        "https://scholens.example/mcp?access_key=secret",
        "https://scholens.example/mcp#fragment",
    ],
)
def test_rejects_unsafe_remote_urls(url: str) -> None:
    with pytest.raises(LocalUploadError):
        validate_remote_url(url)


def test_upload_url_allows_https_presigning_query_but_rejects_remote_http() -> None:
    url = "https://uploads.example.test/source.pdf?X-Amz-Signature=opaque"
    assert validate_upload_url(url) == url
    with pytest.raises(LocalUploadError, match="HTTPS"):
        validate_upload_url("http://uploads.example.test/source.pdf")


def test_local_upload_tool_preserves_ingestion_output_and_truthful_hints() -> None:
    ingest = types.Tool(
        name="ingest_paper",
        inputSchema={"type": "object"},
        outputSchema={"type": "object", "properties": {"result": {}}},
    )

    local = _local_upload_tool([ingest])

    assert local.name == "upload_local_paper"
    assert local.outputSchema == ingest.outputSchema
    assert local.annotations is not None
    assert local.annotations.idempotentHint is False
    assert local.description is not None
    assert "30 MiB" in local.description
    assert local.inputSchema["properties"]["path"]["description"]
    assert "30 MiB" in local.inputSchema["properties"]["path"]["description"]
    assert (
        local.inputSchema["properties"]["wait_seconds"]["maximum"]
        == MAX_TOOL_WAIT_SECONDS
    )


def test_read_only_remote_surface_does_not_advertise_local_upload() -> None:
    remote_tools = [
        types.Tool(name="get_paper", inputSchema={"type": "object"}),
    ]

    assert [tool.name for tool in local_tool_surface(remote_tools)] == ["get_paper"]


def test_write_remote_surface_swaps_prepare_for_local_upload() -> None:
    remote_tools = [
        types.Tool(name="prepare_paper_upload", inputSchema={"type": "object"}),
        types.Tool(
            name="ingest_paper",
            inputSchema={"type": "object"},
            outputSchema={"type": "object"},
        ),
    ]

    assert [tool.name for tool in local_tool_surface(remote_tools)] == [
        "ingest_paper",
        "upload_local_paper",
    ]


@pytest.mark.asyncio
async def test_local_upload_sends_bytes_and_metadata_but_never_the_path(
    tmp_path: Path,
) -> None:
    paper = _pdf(tmp_path / "private-paper.pdf")
    content = paper.read_bytes()
    project_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    upload_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"

    class Remote:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def call_tool(
            self, name: str, arguments: dict[str, object]
        ) -> types.CallToolResult:
            self.calls.append((name, arguments))
            if name == "prepare_paper_upload":
                result = {
                    "upload_id": upload_id,
                    "upload_url": "https://uploads.example.test/source.pdf",
                    "headers": {
                        "content-type": "application/pdf",
                        "x-amz-checksum-sha256": "checksum",
                    },
                }
            else:
                result = {"job_id": "job"}
            return types.CallToolResult(
                content=[],
                structuredContent={"result": result},
                isError=False,
            )

    uploaded: list[httpx.Request] = []

    async def accept_upload(request: httpx.Request) -> httpx.Response:
        uploaded.append(request)
        return httpx.Response(200, request=request)

    remote = Remote()
    async with httpx.AsyncClient(transport=httpx.MockTransport(accept_upload)) as http:
        result = await upload_local_paper(
            remote=remote,
            upload_http=http,
            arguments={
                "path": str(paper),
                "project_id": project_id,
                "idempotency_key": "import-private-paper-v1",
            },
            roots=[tmp_path],
        )

    assert result.isError is False
    assert remote.calls == [
        (
            "prepare_paper_upload",
            {
                "filename": paper.name,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "project_id": project_id,
                "add_to_library": True,
            },
        ),
        (
            "ingest_paper",
            {
                "source": {"kind": "upload", "upload_id": upload_id},
                "project_id": project_id,
                "add_to_library": True,
                "wait_seconds": 30,
                "idempotency_key": "import-private-paper-v1",
            },
        ),
    ]
    assert str(paper) not in repr(remote.calls)
    assert len(uploaded) == 1
    assert uploaded[0].content == content
    assert "authorization" not in uploaded[0].headers
    assert uploaded[0].headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_uncertain_ingestion_returns_exact_last_step_retry(
    tmp_path: Path,
) -> None:
    paper = _pdf(tmp_path / "paper.pdf")
    upload_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"

    class Remote:
        async def call_tool(
            self, name: str, arguments: dict[str, object]
        ) -> types.CallToolResult:
            if name == "prepare_paper_upload":
                return types.CallToolResult(
                    content=[],
                    structuredContent={
                        "result": {
                            "upload_id": upload_id,
                            "upload_url": "https://uploads.example.test/source.pdf",
                            "headers": {"content-type": "application/pdf"},
                        }
                    },
                    isError=False,
                )
            raise McpError(types.ErrorData(code=-32_603, message="unavailable"))

    async def accept_upload(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(accept_upload)) as http:
        result = await upload_local_paper(
            remote=Remote(),
            upload_http=http,
            arguments={
                "path": str(paper),
                "idempotency_key": "stable-import",
            },
            roots=[tmp_path],
        )

    assert result.isError is True
    assert result.structuredContent is None
    error = json.loads(result.content[0].text)["error"]
    assert error["code"] == "local_pdf_ingestion_unavailable"
    assert error["details"] == {
        "retry_arguments": {
            "idempotency_key": "stable-import",
            "project_id": None,
            "add_to_library": True,
            "wait_seconds": 30,
            "source": {"kind": "upload", "upload_id": upload_id},
        },
        "retry_tool": "ingest_paper",
        "upload_id": upload_id,
    }
    assert (
        error["message"]
        == "The ingestion response was unavailable after the PDF transfer"
    )
    assert error["remediation"] == (
        "The PDF transfer completed. Do not upload the file again. Call "
        "ingest_paper with details.retry_arguments exactly as returned; this "
        "preserves both the upload session and idempotency identity."
    )


def test_remote_ingestion_error_preserves_code_and_attaches_retry() -> None:
    source_arguments: dict[str, object] = {
        "source": {"kind": "upload", "upload_id": "upload-id"},
        "idempotency_key": "stable-import",
    }
    remote = types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": {
                            "code": "paper_upload_unavailable",
                            "details": {"diagnostic_id": "diagnostic-id"},
                            "message": "Staging is temporarily unavailable",
                            "remediation": "Retry after a short delay.",
                        }
                    },
                    separators=(",", ":"),
                ),
            )
        ],
        isError=True,
    )

    result = _remote_ingestion_error_with_retry(
        remote,
        upload_id="upload-id",
        source_arguments=source_arguments,
    )

    assert result.structuredContent is None
    error = json.loads(result.content[0].text)["error"]
    assert error["code"] == "paper_upload_unavailable"
    assert error["details"] == {
        "remote_details": {"diagnostic_id": "diagnostic-id"},
        "retry_arguments": source_arguments,
        "retry_tool": "ingest_paper",
        "upload_id": "upload-id",
    }
    assert error["message"] == "Staging is temporarily unavailable"
    assert error["remediation"].startswith("Retry after a short delay.")


def test_remote_ingestion_error_falls_back_when_text_has_no_error_envelope() -> None:
    source_arguments: dict[str, object] = {
        "source": {"kind": "upload", "upload_id": "upload-id"},
    }
    remote = types.CallToolResult(
        content=[types.TextContent(type="text", text="not an error envelope")],
        isError=True,
    )

    result = _remote_ingestion_error_with_retry(
        remote,
        upload_id="upload-id",
        source_arguments=source_arguments,
    )

    assert result.structuredContent is None
    error = json.loads(result.content[0].text)["error"]
    assert error["code"] == "local_pdf_ingestion_unavailable"
    assert error["details"]["retry_tool"] == "ingest_paper"
    assert error["details"]["upload_id"] == "upload-id"


def test_remote_ingestion_error_accepts_legacy_structured_envelope() -> None:
    remote = types.CallToolResult(
        content=[],
        structuredContent={
            "error": {
                "code": "paper_upload_unavailable",
                "message": "Staging is temporarily unavailable",
                "remediation": "Retry after a short delay.",
            }
        },
        isError=True,
    )

    result = _remote_ingestion_error_with_retry(
        remote,
        upload_id="upload-id",
        source_arguments={"source": {"kind": "upload", "upload_id": "upload-id"}},
    )

    error = json.loads(result.content[0].text)["error"]
    assert error["code"] == "paper_upload_unavailable"
    assert error["message"] == "Staging is temporarily unavailable"
