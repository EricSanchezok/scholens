"""Authenticated Streamable HTTP MCP adapter over the canonical tool catalog."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import cast

import mcp.types as mcp_types
from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.access_keys.application.contracts import AuthenticatedAccessKey
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import (
    ApplicationExecutor,
    CredentialKind,
    CredentialRef,
    ErrorEnvelope,
    McpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.application.json_values import (
    JsonNormalizationError,
    normalize_json_value,
)
from app.shared.application.text import json_bounded_prefix
from app.shared.domain import AppError, FailureKind, JsonValue
from app.tooling import (
    ToolAccess,
    ToolCatalog,
    ToolDispatcher,
    ToolExecutionContext,
    ToolResourceLink,
    ToolSourceCandidate,
    serialize_tool_success,
)
from app.tooling.workspace import MCP_TOOL_PROFILE
from app.tooling.error_projection import tool_error_remediation as _error_remediation
from app.transport.client_ip import UNKNOWN_CLIENT_IP, normalize_client_ip
from app.transport.mcp.references import (
    mcp_invocation_id,
    mcp_request_reference,
    mcp_session_reference,
    validate_mcp_session_id,
)
from app.transport.mcp.resource_loader import ScholensResourceLoader
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import request_ctx
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from starlette.types import Message, Receive, Scope, Send
from pydantic import (
    AnyUrl,
    BaseModel,
    Field,
    TypeAdapter,
    create_model,
)
from scholens_observability import (
    DiagnosticSnapshotRecorder,
    NullDiagnosticSnapshotRecorder,
    add_counter,
    build_snapshot,
    current_context,
    log_event,
    update_context,
)

logger = logging.getLogger(__name__)
AccessKeyAuthenticator = Callable[[str], Awaitable[AuthenticatedAccessKey]]
ListToolsHandler = Callable[[], Awaitable[list[mcp_types.Tool]]]
CallToolHandler = Callable[
    [str, dict[str, object]],
    Awaitable[mcp_types.CallToolResult],
]
ListResourcesHandler = Callable[[], Awaitable[list[mcp_types.Resource]]]
ListResourceTemplatesHandler = Callable[[], Awaitable[list[mcp_types.ResourceTemplate]]]
ReadResourceHandler = Callable[[AnyUrl], Awaitable[list[ReadResourceContents]]]

_MCP_RESOURCE_NOT_FOUND = -32002
_MCP_RESOURCE_ACCESS_DENIED = -32003
_MCP_ERROR_DETAILS_MAX_UTF8_BYTES = 8 * 1024
_MCP_ERROR_RESULT_MAX_UTF8_BYTES = 16 * 1024
_MCP_RESOURCE_ERROR_MAX_UTF8_BYTES = 16 * 1024
_MCP_RESOURCE_ERROR_CODE_JSON_BYTES = 256
_MCP_RESOURCE_ERROR_MESSAGE_JSON_BYTES = 2 * 1024
MCP_REQUEST_MAX_BODY_BYTES = 2 * 1024 * 1024

_authenticated_context: ContextVar[AuthenticatedAccessKey | None] = ContextVar(
    "mcp_authenticated_access_key",
    default=None,
)
_client_ip_context: ContextVar[str] = ContextVar(
    "mcp_client_ip",
    default=UNKNOWN_CLIENT_IP,
)
_invocation_session_context: ContextVar[str | None] = ContextVar(
    "mcp_invocation_session",
    default=None,
)
_session_reference_context: ContextVar[str | None] = ContextVar(
    "mcp_session_reference",
    default=None,
)
_request_reference_context: ContextVar[RequestReference | None] = ContextVar(
    "mcp_request_reference",
    default=None,
)


def _strict_json(value: object) -> str:
    return json.dumps(
        normalize_json_value(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _safe_error_details(
    details: dict[str, object] | None,
) -> dict[str, object] | None:
    if details is None:
        return None
    try:
        normalized = normalize_json_value(details)
    except JsonNormalizationError:
        return None
    if not isinstance(normalized, dict):  # pragma: no cover - typed invariant
        return None
    if (
        len(_strict_json(normalized).encode("utf-8"))
        > _MCP_ERROR_DETAILS_MAX_UTF8_BYTES
    ):
        return None
    return cast(dict[str, object], normalized)


def _error_content_text(error: dict[str, object]) -> str:
    text = _strict_json({"error": error})
    if len(text.encode("utf-8")) <= _MCP_ERROR_RESULT_MAX_UTF8_BYTES:
        return text
    bounded = {
        **error,
        "code": (
            error.get("code")
            if isinstance(error.get("code"), str)
            and len(cast(str, error["code"]).encode("utf-8")) <= 256
            else "tool_execution_failed"
        ),
        "message": "The tool call failed; use the error code and diagnostic ID.",
        "remediation": (
            "Review the bounded error code and diagnostic ID; do not retry blindly."
        ),
    }
    bounded.pop("details", None)
    return _strict_json({"error": bounded})


def _error_result(
    *,
    kind: FailureKind,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
    tool_name: str | None = None,
    diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
) -> mcp_types.CallToolResult:
    safe_details = _safe_error_details(details)
    app_error = AppError(
        code=code,
        message=message,
        kind=kind,
        details=safe_details,
    )
    context = current_context()
    snapshot_id = uuid.uuid4() if context.actor_id is not None else None
    if snapshot_id is not None:
        _record_mcp_diagnostic(
            diagnostic_recorder or NullDiagnosticSnapshotRecorder(),
            snapshot_id=snapshot_id,
            code=code,
            kind=kind,
        )
    error = ErrorEnvelope.from_app_error(
        app_error,
        stage="mcp_tool_call",
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        diagnostic_id=str(snapshot_id) if snapshot_id is not None else None,
    ).to_dict()
    replacement_tool = (
        safe_details.get("replacement_tool") if safe_details is not None else None
    )
    error["remediation"] = _error_remediation(
        kind=kind,
        code=code,
        details=safe_details,
        replacement_tool=(
            replacement_tool if isinstance(replacement_tool, str) else None
        ),
        tool_name=tool_name,
    )
    add_counter(
        "scholens.mcp.errors",
        attributes={"code": code, "kind": kind.value},
    )
    log_event(
        logger,
        (
            logging.ERROR
            if kind in {FailureKind.INTERNAL, FailureKind.UNAVAILABLE}
            else logging.WARNING
        ),
        "mcp.request.error",
        error_code=code,
        error_kind=kind.value,
        diagnostic_id=error.get("diagnostic_id"),
    )
    return mcp_types.CallToolResult(
        content=[
            mcp_types.TextContent(
                type="text",
                text=_error_content_text(error),
            )
        ],
        isError=True,
    )


class ToolErrorEnvelope(BaseModel):
    """Compatibility shape retained in the advertised tool output schema.

    Current ``isError`` results omit ``structuredContent`` and serialize this
    shape under ``content[].text.error`` so strict clients do not validate
    errors against stale cached output schemas. Retaining the branch keeps old
    structured error results valid during rolling upgrades.
    """

    code: str
    message: str
    kind: str
    retryable: bool
    remediation: str
    stage: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    diagnostic_id: str | None = None
    details: dict[str, JsonValue] | None = None


class ToolErrorResultEnvelope(BaseModel):
    """The error branch of the advertised output schema (``{error: ...}``)."""

    error: ToolErrorEnvelope


def tool_output_schema(output_model: type[BaseModel]) -> dict[str, object]:
    """Build the exact transport envelope schema for one typed business result.

    The advertised schema accepts both the success envelope (with a required
    ``result``) and the legacy structured error envelope. Current errors omit
    ``structuredContent`` entirely, but the error branch remains for rolling
    compatibility. Both branches are objects, so the union also declares the
    object root required by the negotiated MCP Tool shape instead of relying on
    clients to infer it from ``anyOf`` references.
    """

    success_envelope = create_model(
        f"{output_model.__name__}ToolStructuredResult",
        result=(output_model, ...),
        sources=(list[ToolSourceCandidate], Field(default_factory=list)),
        artifacts=(list[dict[str, JsonValue]], Field(default_factory=list)),
        action=(dict[str, JsonValue] | None, None),
        resource_links=(list[ToolResourceLink], Field(default_factory=list)),
    )
    schema = cast(
        dict[str, object],
        TypeAdapter(success_envelope | ToolErrorResultEnvelope).json_schema(),
    )
    schema["type"] = "object"
    return schema


def _record_mcp_diagnostic(
    recorder: DiagnosticSnapshotRecorder,
    *,
    snapshot_id: uuid.UUID,
    code: str,
    kind: FailureKind,
) -> None:
    context = current_context()
    try:
        recorder.record(
            build_snapshot(
                snapshot_id=snapshot_id,
                service=context.service,
                environment=context.environment,
                release=context.release,
                reason="mcp_request_failed",
                request_id=context.request_id,
                operation_id=context.operation_id,
                correlation_id=context.correlation_id,
                actor_id=context.actor_id,
                sections={
                    "failure": {
                        "code": code,
                        "kind": kind.value,
                        "stage": context.stage or "mcp_tool_call",
                    }
                },
            )
        )
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "diagnostic.snapshot.capture_failed",
            exc_info=exc,
            diagnostic_id=str(snapshot_id),
        )


def _resource_jsonrpc_code(kind: FailureKind) -> int:
    if kind is FailureKind.INVALID_ARGUMENT:
        return mcp_types.INVALID_PARAMS
    if kind is FailureKind.NOT_FOUND:
        return _MCP_RESOURCE_NOT_FOUND
    if kind in {FailureKind.UNAUTHENTICATED, FailureKind.PERMISSION_DENIED}:
        return _MCP_RESOURCE_ACCESS_DENIED
    return mcp_types.INTERNAL_ERROR


def _resource_error(
    error: AppError,
    *,
    diagnostic_recorder: DiagnosticSnapshotRecorder | None,
) -> McpError:
    """Map one application failure to a bounded MCP resource error."""
    try:
        bounded_code = json_bounded_prefix(
            error.code,
            max_bytes=_MCP_RESOURCE_ERROR_CODE_JSON_BYTES,
        )
        safe_code = bounded_code if bounded_code == error.code else "mcp_resource_error"
        safe_message = json_bounded_prefix(
            error.message,
            max_bytes=_MCP_RESOURCE_ERROR_MESSAGE_JSON_BYTES,
        )
    except JsonNormalizationError:
        safe_code = "mcp_resource_error"
        safe_message = "The Scholens resource request failed"
    if not safe_code:
        safe_code = "mcp_resource_error"
    if not safe_message:
        safe_message = "The Scholens resource request failed"
    safe_error = AppError(
        code=safe_code,
        message=safe_message,
        kind=error.kind,
    )
    context = current_context()
    diagnostic_id: uuid.UUID | None = None
    if error.kind in {
        FailureKind.DEPENDENCY_FAILURE,
        FailureKind.UNAVAILABLE,
        FailureKind.INTERNAL,
    }:
        diagnostic_id = uuid.uuid4()
        _record_mcp_diagnostic(
            diagnostic_recorder or NullDiagnosticSnapshotRecorder(),
            snapshot_id=diagnostic_id,
            code=safe_code,
            kind=error.kind,
        )
    envelope = ErrorEnvelope.from_app_error(
        safe_error,
        stage="mcp_resource_read",
        request_id=context.request_id,
        correlation_id=context.correlation_id,
        diagnostic_id=str(diagnostic_id) if diagnostic_id is not None else None,
    ).to_dict()
    # Resource errors never echo arbitrary application details. The stable code,
    # category, remediation, and optional diagnostic ID are sufficient for a
    # client without risking another serialization amplification.
    envelope.pop("details", None)
    envelope["remediation"] = _error_remediation(
        kind=error.kind,
        code=safe_code,
    )
    data = normalize_json_value({"error": envelope})
    rpc_code = _resource_jsonrpc_code(error.kind)
    serialized_error = _strict_json(
        {
            "code": rpc_code,
            "message": safe_message,
            "data": data,
        }
    )
    if len(serialized_error.encode("utf-8")) > _MCP_RESOURCE_ERROR_MAX_UTF8_BYTES:
        safe_code = "mcp_resource_error"
        safe_message = "The Scholens resource request failed"
        fallback = ErrorEnvelope.from_app_error(
            AppError(
                code=safe_code,
                message=safe_message,
                kind=error.kind,
            ),
            stage="mcp_resource_read",
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            diagnostic_id=(str(diagnostic_id) if diagnostic_id is not None else None),
        ).to_dict()
        fallback["remediation"] = (
            "Use the bounded error category and diagnostic ID; do not retry blindly."
        )
        data = normalize_json_value({"error": fallback})
    add_counter(
        "scholens.mcp.errors",
        attributes={"code": safe_code, "kind": error.kind.value},
    )
    log_event(
        logger,
        (
            logging.ERROR
            if error.kind
            in {
                FailureKind.DEPENDENCY_FAILURE,
                FailureKind.UNAVAILABLE,
                FailureKind.INTERNAL,
            }
            else logging.WARNING
        ),
        "mcp.resource.error",
        error_code=safe_code,
        error_kind=error.kind.value,
        diagnostic_id=str(diagnostic_id) if diagnostic_id is not None else None,
    )
    return McpError(
        mcp_types.ErrorData(
            code=rpc_code,
            message=safe_message,
            data=data,
        )
    )


class AuthenticatedMcpApplication:
    """Authenticate one Scholens AccessKey before entering the MCP protocol."""

    def __init__(
        self,
        *,
        manager: StreamableHTTPSessionManager,
        authenticate: AccessKeyAuthenticator,
        diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
    ) -> None:
        self._manager = manager
        self._authenticate = authenticate
        self._diagnostic_recorder = (
            diagnostic_recorder or NullDiagnosticSnapshotRecorder()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        raw_headers = scope.get("headers", [])
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in raw_headers
        }
        authorization = headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            await self._send_auth_error(send, status_code=401)
            return

        try:
            authenticated = await self._authenticate(token)
        except AppError as exc:
            await self._send_auth_error(
                send,
                status_code=(
                    503
                    if exc.kind
                    in {
                        FailureKind.DEPENDENCY_FAILURE,
                        FailureKind.UNAVAILABLE,
                    }
                    else 401
                ),
            )
            return
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "mcp.authentication.failed",
                exc_info=exc,
                error_code="access_key_authentication_unavailable",
            )
            await self._send_auth_error(send, status_code=503)
            return

        client_ip = normalize_client_ip(scope.setdefault("state", {}).get("client_ip"))
        scope.setdefault("state", {})["authenticated"] = True
        scope["state"]["actor_id"] = str(authenticated.actor.id)
        update_context(actor_id=str(authenticated.actor.id), origin="mcp")
        try:
            declared_length = self._declared_content_length(raw_headers)
        except ValueError:
            await self._send_request_error(
                send,
                status_code=400,
                code="mcp_content_length_invalid",
                message="The MCP Content-Length header is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            )
            return
        if declared_length is not None and declared_length > MCP_REQUEST_MAX_BODY_BYTES:
            await self._send_request_error(
                send,
                status_code=413,
                code="mcp_request_too_large",
                message="The MCP request body exceeds the supported limit",
                kind=FailureKind.PAYLOAD_TOO_LARGE,
                details={"maximum_body_bytes": MCP_REQUEST_MAX_BODY_BYTES},
            )
            return

        manager_receive = receive
        if scope.get("method", "").upper() == "POST":
            try:
                first_message = await self._read_request_body(receive)
            except ValueError:
                await self._send_request_error(
                    send,
                    status_code=413,
                    code="mcp_request_too_large",
                    message="The MCP request body exceeds the supported limit",
                    kind=FailureKind.PAYLOAD_TOO_LARGE,
                    details={"maximum_body_bytes": MCP_REQUEST_MAX_BODY_BYTES},
                )
                return
            delivered = False

            async def replay_receive() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return first_message
                return await receive()

            manager_receive = replay_receive
        supplied_session_id = headers.get("mcp-session-id")
        if supplied_session_id is not None:
            try:
                supplied_session_id = validate_mcp_session_id(supplied_session_id)
            except ValueError:
                await self._send_session_error(send)
                return
            invocation_session_id = supplied_session_id
            session_reference = mcp_session_reference(supplied_session_id)
        else:
            invocation_session_id = str(uuid.uuid4())
            session_reference = None
        request_id = scope.setdefault("state", {}).get("request_id")
        request_reference = RequestReference(
            uuid.UUID(str(request_id)) if request_id else uuid.uuid4()
        )
        authenticated_token = _authenticated_context.set(authenticated)
        client_token = _client_ip_context.set(client_ip)
        invocation_session_token = _invocation_session_context.set(
            invocation_session_id
        )
        session_reference_token = _session_reference_context.set(session_reference)
        request_reference_token = _request_reference_context.set(request_reference)
        try:
            await self._manager.handle_request(scope, manager_receive, send)
        finally:
            _request_reference_context.reset(request_reference_token)
            _session_reference_context.reset(session_reference_token)
            _invocation_session_context.reset(invocation_session_token)
            _client_ip_context.reset(client_token)
            _authenticated_context.reset(authenticated_token)

    @staticmethod
    def _declared_content_length(
        raw_headers: list[tuple[bytes, bytes]],
    ) -> int | None:
        values = [
            value.decode("latin-1").strip()
            for key, value in raw_headers
            if key.decode("latin-1").casefold() == "content-length"
        ]
        if not values:
            return None
        if len(values) != 1 or not values[0].isdigit():
            raise ValueError("invalid Content-Length")
        return int(values[0])

    @staticmethod
    async def _read_request_body(receive: Receive) -> Message:
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return message
            chunk = message.get("body", b"")
            if len(chunk) > MCP_REQUEST_MAX_BODY_BYTES - len(body):
                raise ValueError("MCP request body too large")
            body.extend(chunk)
            if not message.get("more_body", False):
                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }

    @staticmethod
    async def _send_request_error(
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
        kind: FailureKind,
        details: dict[str, object] | None = None,
    ) -> None:
        context = current_context()
        error = ErrorEnvelope.from_app_error(
            AppError(code=code, message=message, kind=kind, details=details),
            stage="mcp_request_body",
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            diagnostic_id=None,
        ).to_dict()
        error["remediation"] = _error_remediation(kind=kind, code=code)
        body = _strict_json({"error": error}).encode("utf-8")
        add_counter(
            "scholens.mcp.errors",
            attributes={"code": code, "kind": kind.value},
        )
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _send_auth_error(
        send: Send,
        *,
        status_code: int,
    ) -> None:
        unavailable = status_code == 503
        code = (
            "access_key_authentication_unavailable"
            if unavailable
            else "invalid_access_key"
        )
        message = (
            "Access key authentication is temporarily unavailable"
            if unavailable
            else "The access key is invalid"
        )
        context = current_context()
        error = ErrorEnvelope.from_app_error(
            AppError(
                code=code,
                message=message,
                kind=(
                    FailureKind.UNAVAILABLE
                    if unavailable
                    else FailureKind.UNAUTHENTICATED
                ),
            ),
            stage="mcp_authentication",
            request_id=context.request_id,
            correlation_id=None,
            diagnostic_id=None,
        )
        add_counter(
            "scholens.mcp.authentication_errors",
            attributes={"code": code},
        )
        log_event(
            logger,
            logging.ERROR if unavailable else logging.WARNING,
            "mcp.authentication.error",
            error_code=code,
            status_code=status_code,
        )
        body = json.dumps(
            normalize_json_value({"error": error.to_dict()}),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _send_session_error(self, send: Send) -> None:
        context = current_context()
        snapshot_id = uuid.uuid4()
        _record_mcp_diagnostic(
            self._diagnostic_recorder,
            snapshot_id=snapshot_id,
            code="mcp_session_invalid",
            kind=FailureKind.INVALID_ARGUMENT,
        )
        error = ErrorEnvelope.from_app_error(
            AppError(
                code="mcp_session_invalid",
                message="The MCP session ID is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            ),
            stage="mcp_session",
            request_id=context.request_id,
            correlation_id=None,
            diagnostic_id=str(snapshot_id),
        )
        add_counter(
            "scholens.mcp.errors",
            attributes={
                "code": "mcp_session_invalid",
                "kind": FailureKind.INVALID_ARGUMENT.value,
            },
        )
        log_event(
            logger,
            logging.WARNING,
            "mcp.session.error",
            error_code="mcp_session_invalid",
            diagnostic_id=str(snapshot_id),
        )
        body = json.dumps(
            normalize_json_value({"error": error.to_dict()}),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_mcp_transport(
    *,
    catalog: ToolCatalog[ApplicationCapabilities],
    dispatcher: ToolDispatcher[ApplicationCapabilities],
    executor: ApplicationExecutor[ApplicationCapabilities] | None = None,
    security_settings: TransportSecuritySettings,
    authenticate: AccessKeyAuthenticator,
    operation_factory: OperationContextFactory,
    diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
    web_base_url: str = "https://scholens.local",
) -> tuple[StreamableHTTPSessionManager, AuthenticatedMcpApplication]:
    server: Server[object] = Server(
        "scholens",
        version="1.0.0",
        instructions=(
            "Use Scholens as the durable, permission-aware paper knowledge base for "
            "long-running research. Discover papers with the host Agent's own tools; "
            "Scholens searches only already-stored papers, passages, annotations, "
            "comments, and existing outputs. For repository research, create or get one "
            "Project, then persist its immutable project_id and scholens:// URI in "
            "AGENTS.md or README. Import only known DOI, arXiv, URL, or prepared-upload "
            "sources. Read bounded content before citing it. Risky actions first return "
            "an impact preview and execute only when the same arguments are retried with "
            "the approved confirmation token. Never put credentials or local paths in "
            "tool arguments. Always use a paper result's reader_url as the durable, "
            "user-facing Scholens Markdown link (for example [paper](reader_url)); "
            "keep DOI, arXiv, and source URLs only as provenance. Never persist a "
            "temporary file_url, preview_url, or upload URL."
        ),
    )
    register_list_tools = cast(
        Callable[[], Callable[[ListToolsHandler], ListToolsHandler]],
        server.list_tools,
    )

    @register_list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        authenticated = _authenticated_context.get()
        if authenticated is None:
            return []
        access = ToolAccess(
            profile_name=MCP_TOOL_PROFILE,
            permissions=authenticated.permissions,
        )
        return [
            mcp_types.Tool(
                name=definition.name,
                title=definition.title,
                description=definition.description,
                inputSchema=definition.input_model.model_json_schema(),
                outputSchema=(
                    tool_output_schema(definition.output_model)
                    if definition.output_model is not None
                    else None
                ),
                annotations=(
                    mcp_types.ToolAnnotations(
                        title=definition.title,
                        readOnlyHint=definition.behavior.read_only,
                        destructiveHint=definition.behavior.destructive,
                        idempotentHint=definition.behavior.idempotent,
                        openWorldHint=definition.behavior.open_world,
                    )
                    if definition.behavior is not None
                    else None
                ),
            )
            for definition in catalog.definitions_for(access)
        ]

    register_call_tool = cast(
        Callable[..., Callable[[CallToolHandler], CallToolHandler]],
        server.call_tool,
    )

    @register_call_tool(validate_input=False)
    async def call_tool(
        name: str,
        arguments: dict[str, object],
    ) -> mcp_types.CallToolResult:
        request_started_monotonic = time.monotonic()
        authenticated = _authenticated_context.get()
        if authenticated is None:
            return _error_result(
                kind=FailureKind.UNAUTHENTICATED,
                code="mcp_authentication_required",
                message="Authentication is required",
                diagnostic_recorder=diagnostic_recorder,
            )
        access = ToolAccess(
            profile_name=MCP_TOOL_PROFILE,
            permissions=authenticated.permissions,
        )
        current_request = request_ctx.get()
        invocation_session_id = _invocation_session_context.get()
        request_reference = _request_reference_context.get()
        if invocation_session_id is None or request_reference is None:
            return _error_result(
                kind=FailureKind.UNAUTHENTICATED,
                code="mcp_authentication_required",
                message="Authentication is required",
                diagnostic_recorder=diagnostic_recorder,
            )
        invocation_id = mcp_invocation_id(
            access_key_id=authenticated.access_key_id,
            session_id=invocation_session_id,
            request_id=current_request.request_id,
        )
        operation = operation_factory.root(
            initiated_by=OperationInitiator.AGENT,
            origin=McpOrigin(
                request=request_reference,
                mcp_session_ref=_session_reference_context.get(),
                mcp_request_ref=mcp_request_reference(current_request.request_id),
            ),
            credential=CredentialRef(
                CredentialKind.ACCESS_KEY,
                str(authenticated.access_key_id),
            ),
        )
        update_context(
            actor_id=str(authenticated.actor.id),
            operation_id=str(operation.trace.operation_id),
            correlation_id=str(operation.trace.correlation_id),
            origin="mcp",
            component="tool_dispatcher",
            stage="execute",
        )
        try:
            outcome = await dispatcher.dispatch(
                name=name,
                raw_arguments=arguments,
                context=ToolExecutionContext(
                    actor=authenticated.actor,
                    operation=operation,
                    paper_collection=LibraryPaperCollection(),
                    anchor_document_id=None,
                    invocation_id=invocation_id,
                    client_ip=_client_ip_context.get(),
                    request_started_monotonic=request_started_monotonic,
                    response_reserve_seconds=3.0,
                ),
                access=access,
            )
        except AppError as exc:
            return _error_result(
                kind=exc.kind,
                code=exc.code,
                message=exc.message,
                details=exc.details,
                tool_name=name,
                diagnostic_recorder=diagnostic_recorder,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "mcp.tool.failed",
                exc_info=exc,
                tool_name=name,
                error_code="tool_execution_failed",
            )
            return _error_result(
                kind=FailureKind.UNAVAILABLE,
                code="tool_execution_failed",
                message="Tool execution failed",
                diagnostic_recorder=diagnostic_recorder,
            )

        try:
            serialized = serialize_tool_success(outcome)
        except JsonNormalizationError:
            return _error_result(
                kind=FailureKind.INTERNAL,
                code="tool_result_invalid",
                message="The tool produced an invalid result",
                details={"tool": name},
                diagnostic_recorder=diagnostic_recorder,
            )
        try:
            definition = catalog.definition_for(access, name)
        except KeyError:
            return _error_result(
                kind=FailureKind.NOT_FOUND,
                code="tool_not_found",
                message="Tool not found",
                diagnostic_recorder=diagnostic_recorder,
            )
        if serialized.call_tool_result_utf8_bytes > definition.max_output_bytes:
            details: dict[str, object] = {
                "tool": name,
                "max_output_bytes": definition.max_output_bytes,
                "actual_output_bytes": serialized.call_tool_result_utf8_bytes,
            }
            if definition.replacement_tool is not None:
                details["replacement_tool"] = definition.replacement_tool
            return _error_result(
                kind=FailureKind.INTERNAL,
                code="tool_result_budget_exceeded",
                message="The tool result exceeded its safe output budget",
                details=details,
                diagnostic_recorder=diagnostic_recorder,
            )
        content: list[mcp_types.ContentBlock] = [
            mcp_types.TextContent(
                type="text",
                text=serialized.text_content,
            )
        ]
        content.extend(
            mcp_types.ResourceLink(
                type="resource_link",
                uri=AnyUrl(link.uri),
                name=link.name,
                description=link.description,
                mimeType=link.mime_type,
            )
            for link in serialized.outcome.resource_links
        )
        return mcp_types.CallToolResult(
            content=content,
            structuredContent=serialized.structured_content,
            isError=False,
        )

    resource_loader = (
        ScholensResourceLoader(executor=executor, web_base_url=web_base_url)
        if executor
        else None
    )
    register_list_resources = cast(
        Callable[[], Callable[[ListResourcesHandler], ListResourcesHandler]],
        server.list_resources,
    )

    @register_list_resources()
    async def list_resources() -> list[mcp_types.Resource]:
        authenticated = _authenticated_context.get()
        if (
            authenticated is None
            or not authenticated.can_read_workspace
            or resource_loader is None
        ):
            return []
        return await resource_loader.list_resources(actor=authenticated.actor)

    register_list_resource_templates = cast(
        Callable[
            [],
            Callable[[ListResourceTemplatesHandler], ListResourceTemplatesHandler],
        ],
        server.list_resource_templates,
    )

    @register_list_resource_templates()
    async def list_resource_templates() -> list[mcp_types.ResourceTemplate]:
        authenticated = _authenticated_context.get()
        if authenticated is None or not authenticated.can_read_workspace:
            return []
        return ScholensResourceLoader.list_templates()

    register_read_resource = cast(
        Callable[[], Callable[[ReadResourceHandler], ReadResourceHandler]],
        server.read_resource,
    )

    async def _read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        authenticated = _authenticated_context.get()
        if authenticated is None:
            raise AppError(
                code="mcp_authentication_required",
                message="Authentication is required",
                kind=FailureKind.UNAUTHENTICATED,
            )
        if resource_loader is None:
            raise AppError(
                code="mcp_resources_unavailable",
                message="Scholens resources are unavailable in this server configuration",
                kind=FailureKind.UNAVAILABLE,
            )
        if not authenticated.can_read_workspace:
            raise AppError(
                code="mcp_resource_permission_denied",
                message="Read permission is required for Scholens resources",
                kind=FailureKind.PERMISSION_DENIED,
            )
        return await resource_loader.read(actor=authenticated.actor, uri=uri)

    @register_read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        try:
            return await _read_resource(uri)
        except AppError as exc:
            raise _resource_error(
                exc,
                diagnostic_recorder=diagnostic_recorder,
            ) from exc
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "mcp.resource.failed",
                exc_info=exc,
                error_code="mcp_resource_read_failed",
            )
            raise _resource_error(
                AppError(
                    code="mcp_resource_read_failed",
                    message="The Scholens resource could not be read",
                    kind=FailureKind.INTERNAL,
                ),
                diagnostic_recorder=diagnostic_recorder,
            ) from exc

    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,
        stateless=True,
        security_settings=security_settings,
    )
    application = AuthenticatedMcpApplication(
        manager=manager,
        authenticate=authenticate,
        diagnostic_recorder=diagnostic_recorder,
    )
    return manager, application


__all__ = [
    "AuthenticatedMcpApplication",
    "AccessKeyAuthenticator",
    "build_mcp_transport",
]
