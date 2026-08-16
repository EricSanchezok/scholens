"""Authenticated Streamable HTTP MCP adapter over the canonical tool catalog."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import cast
from urllib.parse import urlsplit

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
from app.shared.domain import AppError, FailureKind, JsonValue
from app.tooling import (
    ToolAccess,
    ToolCatalog,
    ToolDispatcher,
    ToolExecutionContext,
    ToolResourceLink,
    ToolSourceCandidate,
)
from app.tooling.workspace import MCP_TOOL_PROFILE
from app.transport.client_ip import UNKNOWN_CLIENT_IP, normalize_client_ip
from app.transport.mcp.references import (
    mcp_invocation_id,
    mcp_request_reference,
    mcp_session_reference,
    validate_mcp_session_id,
)
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import request_ctx
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import Receive, Scope, Send
from pydantic import (
    AnyUrl,
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
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
_SOURCE_LIST: TypeAdapter[list[ToolSourceCandidate]] = TypeAdapter(
    list[ToolSourceCandidate]
)
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)

AccessKeyAuthenticator = Callable[[str], Awaitable[AuthenticatedAccessKey]]
ListToolsHandler = Callable[[], Awaitable[list[mcp_types.Tool]]]
CallToolHandler = Callable[
    [str, dict[str, object]],
    Awaitable[mcp_types.CallToolResult],
]
ListResourcesHandler = Callable[[], Awaitable[list[mcp_types.Resource]]]
ListResourceTemplatesHandler = Callable[[], Awaitable[list[mcp_types.ResourceTemplate]]]
ReadResourceHandler = Callable[[AnyUrl], Awaitable[list[ReadResourceContents]]]

_MAX_RESOURCE_CHARACTERS = 200_000

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


def _error_result(
    *,
    kind: FailureKind,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
    diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
) -> mcp_types.CallToolResult:
    safe_details: dict[str, object] | None = None
    if details is not None:
        try:
            validated_details = _JSON_VALUE.validate_python(details)
        except ValidationError:
            validated_details = None
        if isinstance(validated_details, dict):
            safe_details = cast(dict[str, object], validated_details)
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
    error["remediation"] = _error_remediation(kind=kind, code=code)
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
                text=json.dumps({"error": error}, separators=(",", ":")),
            )
        ],
        structuredContent={"error": error},
        isError=True,
    )


def _resource_json(*, uri: str, value: object, continuation_tool: str) -> str:
    """Serialize one bounded resource without exposing private storage details."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    validated = _JSON_VALUE.validate_python(value)
    text = json.dumps(validated, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= _MAX_RESOURCE_CHARACTERS:
        return text
    return json.dumps(
        {
            "resource_uri": uri,
            "truncated": True,
            "preview": text[:_MAX_RESOURCE_CHARACTERS],
            "guidance": (
                f"This resource exceeded the bounded MCP representation. Use "
                f"{continuation_tool} with its cursor or range arguments."
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _tool_output_schema(output_model: type[BaseModel]) -> dict[str, object]:
    """Build the exact transport envelope schema for one typed business result."""
    envelope = create_model(
        f"{output_model.__name__}ToolStructuredResult",
        result=(output_model, ...),
        sources=(list[ToolSourceCandidate], Field(default_factory=list)),
        artifacts=(list[dict[str, JsonValue]], Field(default_factory=list)),
        action=(dict[str, JsonValue] | None, None),
        resource_links=(list[ToolResourceLink], Field(default_factory=list)),
    )
    return cast(dict[str, object], envelope.model_json_schema())


def _error_remediation(*, kind: FailureKind, code: str) -> str:
    if code == "tool_arguments_invalid":
        return (
            "Correct the named arguments using this tool's input schema, then call "
            "the same tool again. Do not guess identifiers or opaque cursors."
        )
    if code in {"confirmation_required", "confirmation_stale"}:
        return (
            "Show the returned impact preview to the user. Call the same tool with "
            "unchanged arguments and the returned confirmation token only after approval."
        )
    if kind is FailureKind.PERMISSION_DENIED:
        return (
            "Do not retry unchanged. Ask the user to grant the required Access Key and "
            "resource permission, or choose a resource the caller can access."
        )
    if kind is FailureKind.NOT_FOUND:
        return (
            "Verify the immutable UUID or token with a list/get tool. The resource may "
            "have been deleted or may not be visible to this caller."
        )
    if kind is FailureKind.CONFLICT:
        return (
            "Refresh the affected resource, preserve any supplied idempotency key, and "
            "retry only after adapting to its current state."
        )
    if kind is FailureKind.PAYLOAD_TOO_LARGE:
        return (
            "Use a PDF within the advertised size limit and start a new upload session."
        )
    if kind is FailureKind.RATE_LIMITED:
        return (
            "Wait before retrying; reuse the same idempotency key for the same action."
        )
    if kind in {FailureKind.DEPENDENCY_FAILURE, FailureKind.UNAVAILABLE}:
        return (
            "Retry after a short delay with the same idempotency key. If the failure "
            "persists, report the diagnostic ID to the user."
        )
    if kind is FailureKind.UNAUTHENTICATED:
        return "Reconnect with an active Scholens Access Key; never place the key in tool arguments."
    return "Review the error code and details, correct the request, and avoid blind retries."


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


def _outcome_payload(
    *,
    payload: JsonValue,
    sources: tuple[ToolSourceCandidate, ...],
    artifacts: list[dict[str, JsonValue]],
    action: dict[str, JsonValue] | None,
    resource_links: tuple[object, ...],
) -> dict[str, object]:
    return {
        "result": payload,
        "sources": _SOURCE_LIST.dump_python(list(sources), mode="json"),
        "artifacts": artifacts,
        "action": action,
        "resource_links": [
            {
                "uri": getattr(link, "uri"),
                "name": getattr(link, "name"),
                "description": getattr(link, "description"),
                "mime_type": getattr(link, "mime_type"),
            }
            for link in resource_links
        ],
    }


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
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
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
            await self._manager.handle_request(scope, receive, send)
        finally:
            _request_reference_context.reset(request_reference_token)
            _session_reference_context.reset(session_reference_token)
            _invocation_session_context.reset(invocation_session_token)
            _client_ip_context.reset(client_token)
            _authenticated_context.reset(authenticated_token)

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
            {"error": error.to_dict()},
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
            {"error": error.to_dict()},
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
            "tool arguments."
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
                    _tool_output_schema(definition.output_model)
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
                ),
                access=access,
            )
        except AppError as exc:
            return _error_result(
                kind=exc.kind,
                code=exc.code,
                message=exc.message,
                details=exc.details,
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

        structured = _outcome_payload(
            payload=outcome.payload,
            sources=outcome.sources,
            artifacts=outcome.artifacts,
            action=outcome.action,
            resource_links=cast(tuple[object, ...], outcome.resource_links),
        )
        content: list[mcp_types.ContentBlock] = [
            mcp_types.TextContent(
                type="text",
                text=json.dumps(structured, separators=(",", ":")),
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
            for link in outcome.resource_links
        )
        return mcp_types.CallToolResult(
            content=content,
            structuredContent=structured,
            isError=False,
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
            or executor is None
        ):
            return []
        projects = await asyncio.to_thread(
            executor.query,
            lambda capabilities: capabilities.projects.list(
                actor=authenticated.actor,
                limit=100,
            ),
        )
        resources = [
            mcp_types.Resource(
                uri=AnyUrl("scholens://library"),
                name="library",
                title="Personal Scholens Library",
                description=(
                    "Bounded manifest of saved papers, active ingestions, stored "
                    "outputs, and attention counts."
                ),
                mimeType="application/json",
            ),
            mcp_types.Resource(
                uri=AnyUrl("scholens://projects"),
                name="projects",
                title="Accessible Scholens Projects",
                description=(
                    "Bounded Project index for restoring repository-to-Scholens bindings."
                ),
                mimeType="application/json",
            ),
        ]
        resources.extend(
            mcp_types.Resource(
                uri=AnyUrl(f"scholens://projects/{project.id}"),
                name=f"project-{project.id}",
                title=project.title,
                description=(
                    "Project manifest, papers, collaborators, and existing research outputs."
                ),
                mimeType="application/json",
            )
            for project in projects.items
        )
        return resources

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
        return [
            mcp_types.ResourceTemplate(
                uriTemplate="scholens://papers/{document_id}",
                name="paper",
                title="Scholens paper",
                description="Canonical metadata and a bounded extracted-text preview.",
                mimeType="application/json",
            ),
            mcp_types.ResourceTemplate(
                uriTemplate="scholens://projects/{project_id}",
                name="project",
                title="Scholens Project",
                description="Durable long-running research Project manifest.",
                mimeType="application/json",
            ),
            mcp_types.ResourceTemplate(
                uriTemplate="scholens://annotation-threads/{thread_id}",
                name="annotation-thread",
                title="Scholens annotation thread",
                description="Anchored quote and visible collaborative discussion.",
                mimeType="application/json",
            ),
            mcp_types.ResourceTemplate(
                uriTemplate="scholens://research-outputs/{item_id}",
                name="research-output",
                title="Scholens research output",
                description="Existing citation, audio overview, or data-table output.",
                mimeType="application/json",
            ),
        ]

    register_read_resource = cast(
        Callable[[], Callable[[ReadResourceHandler], ReadResourceHandler]],
        server.read_resource,
    )

    @register_read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        authenticated = _authenticated_context.get()
        if authenticated is None:
            raise AppError(
                code="mcp_authentication_required",
                message="Authentication is required",
                kind=FailureKind.UNAUTHENTICATED,
            )
        if executor is None:
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
        uri_text = str(uri)
        parsed_uri = urlsplit(uri_text)
        if parsed_uri.scheme != "scholens" or parsed_uri.query or parsed_uri.fragment:
            raise AppError(
                code="mcp_resource_uri_invalid",
                message="The Scholens resource URI is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        resource_kind = parsed_uri.netloc
        identifier = parsed_uri.path.strip("/")

        def load(capabilities: ApplicationCapabilities) -> tuple[object, str]:
            actor = authenticated.actor
            if resource_kind == "library" and not identifier:
                return (
                    {
                        "resource_uri": uri_text,
                        "summary": capabilities.paper_library.summary(actor=actor),
                        "papers": capabilities.paper_library.list(
                            actor=actor, limit=50
                        ),
                        "research_outputs": capabilities.paper_library.list_outputs(
                            actor=actor, limit=50
                        ),
                    },
                    "list_library_papers",
                )
            if resource_kind == "projects" and not identifier:
                return (
                    {
                        "resource_uri": uri_text,
                        "projects": capabilities.projects.list(actor=actor, limit=100),
                    },
                    "list_projects",
                )
            try:
                resource_id = uuid.UUID(identifier)
            except ValueError as exc:
                raise AppError(
                    code="mcp_resource_uri_invalid",
                    message="The resource URI must contain a valid UUID",
                    kind=FailureKind.INVALID_ARGUMENT,
                ) from exc
            if resource_kind == "projects":
                project = capabilities.projects.get(actor=actor, project_id=resource_id)
                return (
                    {
                        "resource_uri": uri_text,
                        "project": project,
                        "papers": capabilities.projects.documents(
                            actor=actor,
                            project_id=resource_id,
                            load_urls=False,
                            limit=50,
                        ),
                        "members": capabilities.projects.members(
                            actor=actor, project_id=resource_id
                        ),
                        "research_outputs": capabilities.projects.outputs(
                            actor=actor, project_id=resource_id, limit=50
                        ),
                    },
                    "list_project_papers",
                )
            if resource_kind == "papers":
                capabilities.paper_collection_access(
                    actor=actor,
                    collection=LibraryPaperCollection(),
                    document_id=resource_id,
                    anchor_document_id=None,
                )
                paper = capabilities.paper_details(actor=actor, document_id=resource_id)
                content = capabilities.paper_content.read(
                    actor=actor, document_id=resource_id
                )
                lines = (content.raw_content or "").splitlines()
                return (
                    {
                        "resource_uri": uri_text,
                        "paper": paper,
                        "content_preview": {
                            "start_line": 1,
                            "end_line": min(len(lines), 200),
                            "total_lines": len(lines),
                            "lines": [
                                f"{index}: {line}"
                                for index, line in enumerate(lines[:200], start=1)
                            ],
                            "truncated": len(lines) > 200,
                        },
                        "projects": capabilities.projects.projects_for_document(
                            actor=actor, document_id=resource_id
                        ),
                    },
                    "get_paper_content",
                )
            if resource_kind == "annotation-threads":
                return (
                    {
                        "resource_uri": uri_text,
                        "thread": capabilities.research_items.get_annotation_thread(
                            actor=actor, thread_id=resource_id
                        ),
                    },
                    "get_annotation_thread",
                )
            if resource_kind == "research-outputs":
                item = capabilities.research_items.get_item(
                    actor=actor, item_id=resource_id
                )
                if item.kind.value == "annotation_thread":
                    raise AppError(
                        code="research_output_not_found",
                        message="The resource identifies an annotation thread",
                        kind=FailureKind.NOT_FOUND,
                    )
                return (
                    {"resource_uri": uri_text, "research_output": item},
                    "get_research_output",
                )
            raise AppError(
                code="mcp_resource_not_found",
                message="The Scholens resource kind is not supported",
                kind=FailureKind.NOT_FOUND,
            )

        value, continuation_tool = await asyncio.to_thread(executor.query, load)
        return [
            ReadResourceContents(
                content=_resource_json(
                    uri=uri_text,
                    value=value,
                    continuation_tool=continuation_tool,
                ),
                mime_type="application/json",
            )
        ]

    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
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
