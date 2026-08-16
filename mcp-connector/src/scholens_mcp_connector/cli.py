"""Secure stdio proxy for the remote Scholens Streamable HTTP MCP server."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import unquote, urlparse

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import request_ctx
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl

MAX_PDF_BYTES = 30 * 1024 * 1024
PREPARE_TOOL = "prepare_paper_upload"
LOCAL_UPLOAD_TOOL = "upload_local_paper"
_REMOTE_URL_MAX_LENGTH = 2048
_UPLOAD_URL_MAX_LENGTH = 8192

ListToolsHandler = Callable[[], Awaitable[list[types.Tool]]]
CallToolHandler = Callable[[str, dict[str, object]], Awaitable[types.CallToolResult]]
ListResourcesHandler = Callable[[], Awaitable[list[types.Resource]]]
ListTemplatesHandler = Callable[[], Awaitable[list[types.ResourceTemplate]]]
ReadResourceHandler = Callable[[AnyUrl], Awaitable[list[ReadResourceContents]]]


class LocalUploadError(ValueError):
    """Safe, actionable input error returned to the local Agent."""


class RemoteToolSession(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, object]
    ) -> types.CallToolResult: ...


def _is_loopback_host(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_https_url(
    raw_url: str,
    *,
    purpose: str,
    max_length: int,
    allow_query: bool,
) -> str:
    """Require TLS except for explicit loopback-only local development."""
    if (
        not raw_url
        or raw_url != raw_url.strip()
        or len(raw_url) > max_length
        or any(ord(character) < 32 for character in raw_url)
    ):
        raise LocalUploadError(f"{purpose} URL is malformed")
    try:
        parsed = urlparse(raw_url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise LocalUploadError(f"{purpose} URL is malformed") from exc
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (parsed.query and not allow_query)
    ):
        raise LocalUploadError(f"{purpose} URL is malformed")
    if parsed.scheme == "https":
        return raw_url
    if parsed.scheme == "http" and _is_loopback_host(hostname):
        return raw_url
    raise LocalUploadError(
        f"{purpose} URL must use HTTPS; HTTP is allowed only for loopback development"
    )


def validate_remote_url(raw_url: str) -> str:
    return _validate_https_url(
        raw_url,
        purpose="Scholens MCP",
        max_length=_REMOTE_URL_MAX_LENGTH,
        allow_query=False,
    )


def validate_upload_url(raw_url: str) -> str:
    return _validate_https_url(
        raw_url,
        purpose="Object upload",
        max_length=_UPLOAD_URL_MAX_LENGTH,
        allow_query=True,
    )


def _file_root(uri: AnyUrl) -> Path | None:
    parsed = urlparse(str(uri))
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path)).resolve()


def resolve_local_pdf(raw_path: str, roots: Sequence[Path]) -> Path:
    """Resolve one regular PDF beneath an explicitly exposed client root."""
    if not raw_path or "\x00" in raw_path:
        raise LocalUploadError("path must be a non-empty filesystem path")
    unique_roots = tuple(dict.fromkeys(root.resolve() for root in roots))
    if not unique_roots:
        raise LocalUploadError(
            "No local roots are available. Expose an MCP filesystem root or start "
            "scholens-mcp with --allowed-root for the research workspace."
        )
    supplied = Path(raw_path).expanduser()
    if supplied.is_absolute():
        candidates = [supplied.resolve()]
    else:
        candidates = [
            candidate
            for root in unique_roots
            if (candidate := (root / supplied).resolve()).exists()
        ]
        if len(candidates) != 1:
            raise LocalUploadError(
                "A relative path must identify exactly one file beneath the exposed roots; "
                "use an absolute path when roots contain ambiguous names."
            )
    candidate = candidates[0]
    if not any(candidate.is_relative_to(root) for root in unique_roots):
        raise LocalUploadError("The PDF path is outside every exposed local root")
    if not candidate.is_file():
        raise LocalUploadError("The PDF path must identify an existing regular file")
    if candidate.suffix.casefold() != ".pdf":
        raise LocalUploadError("Only files with a .pdf extension can be uploaded")
    size = candidate.stat().st_size
    if size <= 0 or size > MAX_PDF_BYTES:
        raise LocalUploadError("The PDF must be between 1 byte and 30 MB")
    with candidate.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise LocalUploadError("The selected file does not have a PDF signature")
    return candidate


def _read_bounded_pdf(path: Path) -> bytes:
    """Re-read through a hard byte ceiling in case the file changed after validation."""
    with path.open("rb") as stream:
        content = stream.read(MAX_PDF_BYTES + 1)
    if not content.startswith(b"%PDF-") or len(content) > MAX_PDF_BYTES:
        raise LocalUploadError("The selected file changed or is no longer a valid PDF")
    return content


def _structured_result(result: types.CallToolResult) -> dict[str, Any]:
    if result.isError:
        message = next(
            (
                block.text
                for block in result.content
                if isinstance(block, types.TextContent)
            ),
            "Scholens rejected the request",
        )
        raise LocalUploadError(message)
    structured = result.structuredContent
    if not isinstance(structured, dict) or not isinstance(
        structured.get("result"), dict
    ):
        raise TypeError("Scholens returned an invalid structured tool result")
    return cast(dict[str, Any], structured["result"])


async def _client_roots(configured: Sequence[Path]) -> tuple[Path, ...]:
    roots = list(configured)
    try:
        response = await request_ctx.get().session.list_roots()
    except (McpError, RuntimeError):
        response = None
    if response is not None:
        roots.extend(
            root_path
            for root in response.roots
            if (root_path := _file_root(root.uri)) is not None
        )
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def _local_upload_tool(remote_tools: Sequence[types.Tool]) -> types.Tool:
    ingest = next(tool for tool in remote_tools if tool.name == "ingest_paper")
    return types.Tool(
        name=LOCAL_UPLOAD_TOOL,
        title="Upload local PDF to Scholens",
        description=(
            "Use when a known PDF exists on this computer and should be ingested into "
            "Scholens. Do not use for paper discovery, DOI/arXiv import, directories, "
            "or paths outside MCP roots. The connector reads only the selected PDF, "
            "uploads its exact bytes directly to secure staging, starts ingestion, and "
            "returns no local path. Next: poll get_job with the returned job identity."
        ),
        inputSchema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Absolute path beneath an exposed MCP root, or a relative path "
                        "that identifies exactly one PDF beneath those roots."
                    ),
                },
                "project_id": {
                    "type": ["string", "null"],
                    "format": "uuid",
                    "description": (
                        "Optional immutable Scholens Project UUID. Read it from repository "
                        "guidance or a Project tool; never infer it from the title."
                    ),
                },
                "idempotency_key": {
                    "type": ["string", "null"],
                    "minLength": 1,
                    "maxLength": 200,
                    "description": (
                        "Stable key for this one logical ingestion. Reuse it after an "
                        "uncertain response; use a new key for a genuinely new import."
                    ),
                },
            },
            "required": ["path"],
        },
        outputSchema=ingest.outputSchema,
        annotations=types.ToolAnnotations(
            title="Upload local PDF to Scholens",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )


def local_tool_surface(remote_tools: Sequence[types.Tool]) -> list[types.Tool]:
    """Swap the upload primitive only when the credential can use both steps."""
    visible = [tool for tool in remote_tools if tool.name != PREPARE_TOOL]
    remote_names = {tool.name for tool in remote_tools}
    if {PREPARE_TOOL, "ingest_paper"}.issubset(remote_names):
        visible.append(_local_upload_tool(remote_tools))
    return sorted(visible, key=lambda tool: tool.name)


def _local_error_result(
    *,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
    remediation: str | None = None,
) -> types.CallToolResult:
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "remediation": remediation
        or (
            "Choose one PDF inside an exposed MCP root and retry. Keep the same "
            "idempotency_key only when retrying the same logical import."
        ),
    }
    if details is not None:
        error["details"] = details
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps({"error": error}, separators=(",", ":")),
            )
        ],
        structuredContent={"error": error},
        isError=True,
    )


def _ingestion_retry_result(
    *,
    upload_id: str,
    source_arguments: dict[str, object],
    message: str,
) -> types.CallToolResult:
    return _local_error_result(
        code="local_pdf_ingestion_unavailable",
        message=message,
        details={
            "upload_id": upload_id,
            "retry_tool": "ingest_paper",
            "retry_arguments": source_arguments,
        },
        remediation=(
            "The PDF transfer completed. Do not upload the file again. Call ingest_paper "
            "with details.retry_arguments exactly as returned; this preserves both the "
            "upload session and idempotency identity."
        ),
    )


def _remote_ingestion_error_with_retry(
    result: types.CallToolResult,
    *,
    upload_id: str,
    source_arguments: dict[str, object],
) -> types.CallToolResult:
    """Preserve the Scholens error while attaching a safe exact-step continuation."""
    structured = result.structuredContent
    remote_error = structured.get("error") if isinstance(structured, dict) else None
    if not isinstance(remote_error, dict):
        return _ingestion_retry_result(
            upload_id=upload_id,
            source_arguments=source_arguments,
            message="Scholens returned an invalid ingestion error after the PDF transfer",
        )
    error = dict(remote_error)
    prior_details = error.get("details")
    details: dict[str, object] = {
        "upload_id": upload_id,
        "retry_tool": "ingest_paper",
        "retry_arguments": source_arguments,
    }
    if prior_details is not None:
        details["remote_details"] = prior_details
    error["details"] = details
    prior_remediation = error.get("remediation")
    continuation = (
        "If this error is retryable or the outcome remains uncertain, do not upload "
        "again; call ingest_paper with details.retry_arguments exactly as returned."
    )
    error["remediation"] = (
        f"{prior_remediation} {continuation}"
        if isinstance(prior_remediation, str) and prior_remediation
        else continuation
    )
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps({"error": error}, separators=(",", ":")),
            )
        ],
        structuredContent={"error": error},
        isError=True,
    )


async def upload_local_paper(
    *,
    remote: RemoteToolSession,
    upload_http: httpx.AsyncClient,
    arguments: dict[str, object],
    roots: Sequence[Path],
) -> types.CallToolResult:
    """Upload one root-authorized local PDF without sending its path remotely."""
    raw_path = arguments.get("path")
    if not isinstance(raw_path, str):
        raise LocalUploadError("path must be a string")
    path = resolve_local_pdf(raw_path, roots)
    content = await asyncio.to_thread(_read_bounded_pdf, path)
    digest = hashlib.sha256(content).hexdigest()
    project_id = arguments.get("project_id")
    idempotency_key = arguments.get("idempotency_key")
    prepare = await remote.call_tool(
        PREPARE_TOOL,
        {
            "filename": path.name,
            "size_bytes": len(content),
            "sha256": digest,
            "project_id": project_id,
        },
    )
    prepared = _structured_result(prepare)
    upload_url = prepared.get("upload_url")
    upload_headers = prepared.get("headers")
    upload_id = prepared.get("upload_id")
    if (
        not isinstance(upload_url, str)
        or not isinstance(upload_headers, dict)
        or not isinstance(upload_id, str)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in upload_headers.items()
        )
    ):
        raise RuntimeError("Scholens returned invalid upload preparation")
    upload_response = await upload_http.put(
        validate_upload_url(upload_url),
        headers=cast(dict[str, str], upload_headers),
        content=content,
    )
    upload_response.raise_for_status()
    source_arguments: dict[str, object] = {
        "source": {"kind": "upload", "upload_id": upload_id},
        "project_id": project_id,
    }
    if idempotency_key is not None:
        source_arguments["idempotency_key"] = idempotency_key
    try:
        result = await remote.call_tool("ingest_paper", source_arguments)
    except (McpError, httpx.RequestError, RuntimeError, TypeError):
        return _ingestion_retry_result(
            upload_id=upload_id,
            source_arguments=source_arguments,
            message="The ingestion response was unavailable after the PDF transfer",
        )
    if result.isError:
        return _remote_ingestion_error_with_retry(
            result,
            upload_id=upload_id,
            source_arguments=source_arguments,
        )
    return result


async def _run(*, remote_url: str, access_key: str, roots: Sequence[Path]) -> None:
    remote_url = validate_remote_url(remote_url)
    remote_http = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {access_key}"},
        timeout=httpx.Timeout(60),
        follow_redirects=False,
    )
    upload_http = httpx.AsyncClient(
        timeout=httpx.Timeout(120),
        follow_redirects=False,
    )
    try:
        async with (
            streamable_http_client(remote_url, http_client=remote_http) as (
                remote_read,
                remote_write,
                _session_id,
            ),
            ClientSession(remote_read, remote_write) as remote,
        ):
            await remote.initialize()
            local: Server[object] = Server(
                "scholens-local",
                version="0.1.0",
                instructions=(
                    "Use Scholens as the durable paper knowledge base for this research "
                    "workspace. Discover papers with the host Agent's own tools; Scholens "
                    "searches only stored knowledge. Persist the immutable project_id and "
                    "scholens:// URI returned by create_project or get_project in AGENTS.md "
                    "or README. Use upload_local_paper only for one PDF beneath an exposed "
                    "root; never send a local path to a remote tool. Present impact previews "
                    "before retrying risky actions with their confirmation tokens."
                ),
            )

            register_list_tools = cast(
                Callable[[], Callable[[ListToolsHandler], ListToolsHandler]],
                local.list_tools,
            )

            @register_list_tools()
            async def list_tools() -> list[types.Tool]:
                result = await remote.list_tools()
                return local_tool_surface(result.tools)

            register_call_tool = cast(
                Callable[..., Callable[[CallToolHandler], CallToolHandler]],
                local.call_tool,
            )

            @register_call_tool(validate_input=False)
            async def call_tool(
                name: str, arguments: dict[str, object]
            ) -> types.CallToolResult:
                if name != LOCAL_UPLOAD_TOOL:
                    return await remote.call_tool(name, dict(arguments))
                try:
                    return await upload_local_paper(
                        remote=remote,
                        upload_http=upload_http,
                        arguments=dict(arguments),
                        roots=await _client_roots(roots),
                    )
                except LocalUploadError as exc:
                    return _local_error_result(
                        code="local_pdf_invalid",
                        message=str(exc),
                    )
                except httpx.HTTPStatusError:
                    return _local_error_result(
                        code="local_pdf_upload_failed",
                        message="The secure PDF upload was rejected",
                    )
                except (McpError, httpx.RequestError, RuntimeError, TypeError):
                    return _local_error_result(
                        code="local_pdf_upload_unavailable",
                        message="The local PDF upload could not be completed",
                    )

            register_list_resources = cast(
                Callable[[], Callable[[ListResourcesHandler], ListResourcesHandler]],
                local.list_resources,
            )

            @register_list_resources()
            async def list_resources() -> list[types.Resource]:
                return (await remote.list_resources()).resources

            register_list_templates = cast(
                Callable[[], Callable[[ListTemplatesHandler], ListTemplatesHandler]],
                local.list_resource_templates,
            )

            @register_list_templates()
            async def list_resource_templates() -> list[types.ResourceTemplate]:
                return (await remote.list_resource_templates()).resourceTemplates

            register_read_resource = cast(
                Callable[[], Callable[[ReadResourceHandler], ReadResourceHandler]],
                local.read_resource,
            )

            @register_read_resource()
            async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
                result = await remote.read_resource(uri)
                return [
                    ReadResourceContents(
                        content=(
                            item.text
                            if isinstance(item, types.TextResourceContents)
                            else item.blob
                        ),
                        mime_type=item.mimeType,
                    )
                    for item in result.contents
                ]

            async with stdio_server() as (local_read, local_write):
                await local.run(
                    local_read,
                    local_write,
                    local.create_initialization_options(),
                )
    finally:
        await upload_http.aclose()
        await remote_http.aclose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholens-mcp",
        description="Run the local Scholens MCP stdio connector.",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("SCHOLENS_MCP_URL"),
        help="Remote Scholens MCP URL (or SCHOLENS_MCP_URL).",
    )
    parser.add_argument(
        "--access-key",
        default=os.getenv("SCHOLENS_ACCESS_KEY"),
        help="Scholens access key (prefer SCHOLENS_ACCESS_KEY).",
    )
    parser.add_argument(
        "--allowed-root",
        action="append",
        default=[],
        type=Path,
        help="Additional local directory allowed for PDF paths; repeat as needed.",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if not args.url or not args.access_key:
        print(
            "SCHOLENS_MCP_URL and SCHOLENS_ACCESS_KEY are required",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        asyncio.run(
            _run(
                remote_url=cast(str, args.url),
                access_key=cast(str, args.access_key),
                roots=cast(list[Path], args.allowed_root),
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
