from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.access_keys.application.contracts import AuthenticatedAccessKey
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    CredentialKind,
    CredentialRef,
    McpOrigin,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.tooling import (
    ToolAccess,
    ToolCatalog,
    ToolExecutionContext,
    ToolDefinition,
    ToolDispatcher,
    ToolExecutionKind,
    ToolOutcome,
    ToolProfile,
    ToolResourceLink,
    serialize_tool_success,
)
from app.tooling.workspace import build_workspace_tool_catalog
from app.tooling.workspace_contracts import (
    CreateAnnotationThreadInput,
    IngestPapersInput,
)
from app.transport.mcp.server import (
    MCP_REQUEST_MAX_BODY_BYTES,
    AuthenticatedMcpApplication,
    _error_remediation,
    build_mcp_transport,
)
from httpx import ASGITransport, AsyncClient
from mcp.server.transport_security import TransportSecuritySettings
import json
import pytest
from pydantic import BaseModel, ConfigDict
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

ACCESS_KEY_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ACCESS_KEY_SECRET = "sk_scholens_" + "a" * 43


def test_replacement_tool_guidance_applies_to_non_transport_budget_errors() -> None:
    remediation = _error_remediation(
        kind=FailureKind.PAYLOAD_TOO_LARGE,
        code="legacy_research_output_list_too_large",
        replacement_tool="list_research_output_summaries",
    )

    assert "Use list_research_output_summaries" in remediation
    assert "smaller PDF" not in remediation


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[
            tuple[str, dict[str, object], ToolExecutionContext, ToolAccess]
        ] = []
        self.error: AppError | None = None
        self.outcome: ToolOutcome | None = None

    async def dispatch(
        self,
        *,
        name: str,
        raw_arguments: dict[str, object],
        context: ToolExecutionContext,
        access: ToolAccess,
    ) -> ToolOutcome:
        self.calls.append((name, raw_arguments, context, access))
        if self.error is not None:
            raise self.error
        if self.outcome is not None:
            return self.outcome
        return ToolOutcome(payload={"tool": name, "arguments": raw_arguments})


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MinimalCapabilities:
    pass


class MinimalExecutor:
    def query(
        self,
        operation: Callable[[MinimalCapabilities], Any],
    ) -> Any:
        return operation(MinimalCapabilities())


class RecordingMcpManager:
    def __init__(self) -> None:
        self.calls = 0
        self.first_message: Message | None = None

    async def handle_request(
        self, _scope: Scope, receive: Receive, _send: Send
    ) -> None:
        self.calls += 1
        self.first_message = await receive()


def _authenticated_endpoint(
    manager: RecordingMcpManager,
) -> AuthenticatedMcpApplication:
    async def authenticate(_token: str) -> AuthenticatedAccessKey:
        return AuthenticatedAccessKey(
            access_key_id=ACCESS_KEY_ID,
            actor=_actor(),
            permissions=frozenset(WorkspacePermission),
        )

    return AuthenticatedMcpApplication(
        manager=cast(Any, manager),
        authenticate=authenticate,
    )


def _unexpected_handler(
    _capabilities: MinimalCapabilities,
    _context: ToolExecutionContext,
    _arguments: EmptyInput,
) -> ToolOutcome:
    raise AssertionError("an unavailable tool must not execute")


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _application(
    catalog: ToolCatalog[Any],
    dispatcher: object,
    *,
    permissions: (
        frozenset[WorkspacePermission] | Callable[[], frozenset[WorkspacePermission]]
    ) = frozenset(WorkspacePermission),
    executor: object | None = None,
) -> Starlette:
    async def authenticate(token: str) -> AuthenticatedAccessKey:
        if token != ACCESS_KEY_SECRET:
            raise AppError(
                kind=FailureKind.UNAUTHENTICATED,
                code="invalid_access_key",
                message="The access key is invalid",
            )
        return AuthenticatedAccessKey(
            access_key_id=ACCESS_KEY_ID,
            actor=_actor(),
            permissions=permissions() if callable(permissions) else permissions,
        )

    manager, endpoint = build_mcp_transport(
        catalog=cast(ToolCatalog[ApplicationCapabilities], catalog),
        dispatcher=cast(
            ToolDispatcher[ApplicationCapabilities],
            dispatcher,
        ),
        executor=cast(ApplicationExecutor[ApplicationCapabilities] | None, executor),
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["testserver"],
            allowed_origins=[],
        ),
        authenticate=authenticate,
        operation_factory=OperationContextFactory(),
    )

    @asynccontextmanager
    async def lifespan(_application: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    return Starlette(
        routes=[Route("/mcp", endpoint=endpoint)],
        lifespan=lifespan,
    )


def _transport() -> tuple[Starlette, RecordingDispatcher]:
    catalog = build_workspace_tool_catalog(
        ingestion=cast(PaperIngestionWorkflow, object()),
        citations=cast(CitationWorkflow, object()),
    )
    recording = RecordingDispatcher()
    return _application(catalog, recording), recording


async def _initialize(client: AsyncClient) -> dict[str, str]:
    headers = {
        "authorization": f"Bearer {ACCESS_KEY_SECRET}",
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    response = await client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": "initialize",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        },
    )
    assert response.status_code == 200
    initialized_headers = {
        **headers,
        "mcp-protocol-version": "2025-11-25",
    }
    session_id = response.headers.get("mcp-session-id")
    if session_id is not None:
        initialized_headers["mcp-session-id"] = session_id
    return initialized_headers


def _request_scope(*, content_length: int | None = None) -> Scope:
    headers = [(b"authorization", f"Bearer {ACCESS_KEY_SECRET}".encode())]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    return cast(
        Scope,
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/mcp",
            "raw_path": b"/mcp",
            "query_string": b"",
            "headers": headers,
            "state": {},
        },
    )


@pytest.mark.asyncio
async def test_mcp_rejects_declared_oversized_body_before_manager_entry() -> None:
    manager = RecordingMcpManager()
    endpoint = _authenticated_endpoint(manager)
    sent: list[Message] = []

    async def receive() -> Message:
        raise AssertionError("declared oversized body must not be read")

    async def send(message: Message) -> None:
        sent.append(message)

    await endpoint(
        _request_scope(content_length=MCP_REQUEST_MAX_BODY_BYTES + 1),
        receive,
        send,
    )

    assert manager.calls == 0
    assert sent[0]["status"] == 413
    error = json.loads(sent[-1]["body"])["error"]
    assert error["code"] == "mcp_request_too_large"
    assert error["details"]["maximum_body_bytes"] == MCP_REQUEST_MAX_BODY_BYTES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_length_headers",
    [
        [(b"content-length", b"1"), (b"Content-Length", b"1")],
        [(b"content-length", b"not-a-number")],
        [(b"content-length", b"-1")],
    ],
)
async def test_mcp_rejects_ambiguous_or_invalid_content_length(
    content_length_headers: list[tuple[bytes, bytes]],
) -> None:
    manager = RecordingMcpManager()
    endpoint = _authenticated_endpoint(manager)
    sent: list[Message] = []
    scope = _request_scope()
    scope["headers"].extend(content_length_headers)

    async def receive() -> Message:
        raise AssertionError("invalid Content-Length must be rejected before body read")

    async def send(message: Message) -> None:
        sent.append(message)

    await endpoint(scope, receive, send)

    assert manager.calls == 0
    assert sent[0]["status"] == 400
    error = json.loads(sent[-1]["body"])["error"]
    assert error["code"] == "mcp_content_length_invalid"


@pytest.mark.asyncio
async def test_mcp_stops_chunked_body_at_the_first_overflow() -> None:
    manager = RecordingMcpManager()
    endpoint = _authenticated_endpoint(manager)
    sent: list[Message] = []
    events = iter(
        [
            {
                "type": "http.request",
                "body": b"a" * MCP_REQUEST_MAX_BODY_BYTES,
                "more_body": True,
            },
            {"type": "http.request", "body": b"b", "more_body": True},
            {"type": "http.request", "body": b"must-not-read", "more_body": False},
        ]
    )
    read_count = 0

    async def receive() -> Message:
        nonlocal read_count
        read_count += 1
        return cast(Message, next(events))

    async def send(message: Message) -> None:
        sent.append(message)

    await endpoint(_request_scope(), receive, send)

    assert manager.calls == 0
    assert read_count == 2
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_mcp_accepts_a_body_at_the_exact_wire_limit() -> None:
    manager = RecordingMcpManager()
    endpoint = _authenticated_endpoint(manager)
    body = b" " * MCP_REQUEST_MAX_BODY_BYTES
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(_message: Message) -> None:
        return None

    await endpoint(
        _request_scope(content_length=MCP_REQUEST_MAX_BODY_BYTES),
        receive,
        send,
    )

    assert manager.calls == 1
    assert manager.first_message is not None
    assert manager.first_message["body"] == body


def test_largest_legal_tool_arguments_fit_the_mcp_wire_limit() -> None:
    maximum_integer = (1 << 31) - 1
    rect = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.004}
    annotation = CreateAnnotationThreadInput.model_validate(
        {
            "document_id": str(UUID(int=1)),
            "quote_text": "界" * 100_000,
            "position": {
                "kind": "pdf_text",
                "page_number": maximum_integer,
                "rects": [rect] * 200,
            },
            "audience": {"kind": "personal"},
            "initial_comment": "界" * 100_000,
        }
    )
    url_prefix = "https://example.com/"
    url = url_prefix + "a" * (2_048 - len(url_prefix))
    ingestion = IngestPapersInput.model_validate(
        {"sources": [{"kind": "url", "url": url}] * 50}
    )

    for name, arguments in (
        ("create_annotation_thread", annotation),
        ("ingest_papers", ingestion),
    ):
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": name,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments.model_dump(mode="json"),
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        assert len(body) < MCP_REQUEST_MAX_BODY_BYTES


@pytest.mark.asyncio
async def test_mcp_requires_a_valid_scholens_access_key() -> None:
    application, _ = _transport()
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            missing = await client.post("/mcp", json={})
            revoked = await client.post(
                "/mcp",
                headers={"authorization": "Bearer sanchezcloud-identity-access-token"},
                json={},
            )

    assert missing.status_code == 401
    assert revoked.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_access_key"
    assert revoked.json()["error"]["code"] == "invalid_access_key"


@pytest.mark.asyncio
async def test_mcp_lists_catalog_tools_and_dispatches_with_bound_actor() -> None:
    application, dispatcher = _transport()
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            listed = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "list-tools",
                    "method": "tools/list",
                    "params": {},
                },
            )
            called = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-tool",
                    "method": "tools/call",
                    "params": {
                        "name": "list_projects",
                        "arguments": {"limit": 10},
                    },
                },
            )

    tools = listed.json()["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    tools_by_name = {tool["name"]: tool for tool in tools}
    assert len(tool_names) == 64
    assert "ingest_papers" in tool_names
    assert "wait_for_jobs" not in tool_names
    assert "finish_tool_use" not in tool_names
    assert "search_papers" not in tool_names
    assert tools_by_name["list_projects"]["title"] == "List Projects"
    assert tools_by_name["list_projects"]["annotations"] == {
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
        "readOnlyHint": True,
        "title": "List Projects",
    }
    assert tools_by_name["create_project"]["annotations"]["idempotentHint"] is False
    assert tools_by_name["update_project"]["annotations"]["idempotentHint"] is True
    assert tools_by_name["delete_project"]["annotations"]["destructiveHint"] is True
    assert (
        tools_by_name["prepare_paper_upload"]["annotations"]["idempotentHint"] is False
    )
    get_project_schema = tools_by_name["get_project"]["outputSchema"]
    assert "anyOf" in get_project_schema
    assert len(get_project_schema["anyOf"]) == 2
    assert tools_by_name["get_project"]["inputSchema"]["properties"]["project_id"][
        "description"
    ]
    assert called.json()["result"]["structuredContent"]["result"] == {
        "tool": "list_projects",
        "arguments": {"limit": 10},
    }
    name, arguments, context, access = dispatcher.calls[0]
    assert name == "list_projects"
    assert arguments == {"limit": 10}
    assert context.actor.id == 7
    assert context.operation.initiated_by is OperationInitiator.AGENT
    assert isinstance(context.operation.origin, McpOrigin)
    assert context.operation.credential == CredentialRef(
        CredentialKind.ACCESS_KEY,
        str(ACCESS_KEY_ID),
    )
    assert context.paper_collection.kind == "library"
    assert context.anchor_document_id is None
    assert access.permissions == frozenset(WorkspacePermission)
    assert context.invocation_id.startswith("mcp:")
    assert len(context.invocation_id) == 68
    assert ACCESS_KEY_SECRET not in context.invocation_id


@pytest.mark.asyncio
async def test_mcp_advertises_bounded_scholens_resource_templates_and_projects() -> (
    None
):
    project_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    class Projects:
        def resource_catalog(self, **_arguments: object) -> object:
            return [
                SimpleNamespace(id=project_id, title="Chain-of-thought compression")
            ]

    class Capabilities:
        projects = Projects()

    class Executor:
        def query(self, operation: Callable[[Capabilities], Any]) -> Any:
            return operation(Capabilities())

    catalog = build_workspace_tool_catalog(
        ingestion=cast(PaperIngestionWorkflow, object()),
        citations=cast(CitationWorkflow, object()),
    )
    application = _application(
        catalog,
        RecordingDispatcher(),
        executor=Executor(),
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            resources = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "list-resources",
                    "method": "resources/list",
                    "params": {},
                },
            )
            templates = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "list-resource-templates",
                    "method": "resources/templates/list",
                    "params": {},
                },
            )

    resource_uris = {item["uri"] for item in resources.json()["result"]["resources"]}
    assert resource_uris == {
        "scholens://library",
        "scholens://projects",
        f"scholens://projects/{project_id}",
    }
    template_uris = {
        item["uriTemplate"] for item in templates.json()["result"]["resourceTemplates"]
    }
    assert template_uris == {
        "scholens://papers/{document_id}",
        "scholens://projects/{project_id}",
        "scholens://annotation-threads/{thread_id}",
        "scholens://research-outputs/{item_id}",
    }


@pytest.mark.asyncio
async def test_mcp_tool_list_uses_access_key_permission_snapshot() -> None:
    catalog = build_workspace_tool_catalog(
        ingestion=cast(PaperIngestionWorkflow, object()),
        citations=cast(CitationWorkflow, object()),
    )
    application = _application(
        catalog,
        RecordingDispatcher(),
        permissions=frozenset({WorkspacePermission.READ}),
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "list-tools",
                    "method": "tools/list",
                    "params": {},
                },
            )

    tool_names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert "search_scholens_knowledge" in tool_names
    assert "search_papers" not in tool_names
    assert "create_project" not in tool_names
    assert "delete_project" not in tool_names
    assert "finish_tool_use" not in tool_names


@pytest.mark.asyncio
async def test_mcp_reauthenticates_permissions_on_each_request() -> None:
    catalog = build_workspace_tool_catalog(
        ingestion=cast(PaperIngestionWorkflow, object()),
        citations=cast(CitationWorkflow, object()),
    )
    current_permissions = frozenset({WorkspacePermission.READ})
    application = _application(
        catalog,
        RecordingDispatcher(),
        permissions=lambda: current_permissions,
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            before = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "list-before-permission-change",
                    "method": "tools/list",
                    "params": {},
                },
            )
            current_permissions = frozenset(
                {WorkspacePermission.READ, WorkspacePermission.WRITE}
            )
            after = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "list-after-permission-change",
                    "method": "tools/list",
                    "params": {},
                },
            )

    before_names = {tool["name"] for tool in before.json()["result"]["tools"]}
    after_names = {tool["name"] for tool in after.json()["result"]["tools"]}
    assert "create_project" not in before_names
    assert "create_project" in after_names


@pytest.mark.asyncio
async def test_mcp_tool_call_enforces_the_same_permission_snapshot() -> None:
    catalog = ToolCatalog(
        [
            ToolDefinition(
                name="write_only",
                description="A write-only test tool.",
                input_model=EmptyInput,
                execution=ToolExecutionKind.QUERY,
                required_permission=WorkspacePermission.WRITE,
                handler=_unexpected_handler,
            )
        ],
        [ToolProfile(name="mcp", tool_names=frozenset({"write_only"}))],
    )
    dispatcher = ToolDispatcher(catalog=catalog, executor=MinimalExecutor())
    application = _application(
        catalog,
        dispatcher,
        permissions=frozenset({WorkspacePermission.READ}),
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-unavailable-tool",
                    "method": "tools/call",
                    "params": {
                        "name": "write_only",
                        "arguments": {"invalid": "must not be validated"},
                    },
                },
            )

    error = json.loads(response.json()["result"]["content"][0]["text"])["error"]
    assert "structuredContent" not in response.json()["result"]
    assert error["kind"] == "not_found"
    assert error["code"] == "tool_not_found"
    assert error["message"] == "Tool not found"
    assert error.get("details") is None
    assert error["retryable"] is False
    assert error["stage"] == "mcp_tool_call"


@pytest.mark.asyncio
async def test_mcp_maps_application_errors_to_structured_tool_errors() -> None:
    application, dispatcher = _transport()
    dispatcher.error = AppError(
        kind=FailureKind.PERMISSION_DENIED,
        code="project_access_denied",
        message="Project access denied",
        details={"project_id": "missing"},
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-tool",
                    "method": "tools/call",
                    "params": {
                        "name": "list_projects",
                        "arguments": {},
                    },
                },
            )

    result = response.json()["result"]
    assert result["isError"] is True
    assert "structuredContent" not in result
    error = json.loads(result["content"][0]["text"])["error"]
    assert error["kind"] == "permission_denied"
    assert error["code"] == "project_access_denied"
    assert error["message"] == "Project access denied"
    assert error["details"] == {"project_id": "missing"}
    assert error["retryable"] is False
    assert error["stage"] == "mcp_tool_call"


@pytest.mark.asyncio
async def test_mcp_omits_nonfinite_or_oversized_application_error_details() -> None:
    application, dispatcher = _transport()
    dispatcher.error = AppError(
        kind=FailureKind.CONFLICT,
        code="test_conflict",
        message="Test conflict",
        details={"score": float("nan"), "diagnostic": "x" * 100_000},
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-tool",
                    "method": "tools/call",
                    "params": {"name": "list_projects", "arguments": {}},
                },
            )

    assert "NaN" not in response.text
    assert "Infinity" not in response.text
    assert len(response.content) < 16 * 1024
    error = json.loads(response.json()["result"]["content"][0]["text"])["error"]
    assert error["code"] == "test_conflict"
    assert "details" not in error


@pytest.mark.asyncio
async def test_mcp_maps_a_nonfinite_tool_success_to_a_strict_json_error() -> None:
    catalog = ToolCatalog(
        [
            ToolDefinition(
                name="strict_result",
                description="Return a strict result.",
                input_model=EmptyInput,
                execution=ToolExecutionKind.QUERY,
                required_permission=WorkspacePermission.READ,
                handler=lambda capabilities, context, arguments: ToolOutcome(
                    payload={"score": float("nan")}
                ),
            )
        ],
        [ToolProfile(name="mcp", tool_names=frozenset({"strict_result"}))],
    )
    application = _application(
        catalog,
        ToolDispatcher(catalog=catalog, executor=MinimalExecutor()),
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "strict-result",
                    "method": "tools/call",
                    "params": {"name": "strict_result", "arguments": {}},
                },
            )

    assert "NaN" not in response.text
    result = response.json()["result"]
    assert result["isError"] is True
    error = json.loads(result["content"][0]["text"])["error"]
    assert error["code"] == "tool_result_invalid"
    assert error["kind"] == "internal"


@pytest.mark.asyncio
async def test_mcp_rejects_a_nonfinite_tool_argument_as_strict_json() -> None:
    class NumericInput(BaseModel):
        value: float

    catalog = ToolCatalog(
        [
            ToolDefinition(
                name="strict_argument",
                description="Accept a finite number.",
                input_model=NumericInput,
                execution=ToolExecutionKind.QUERY,
                required_permission=WorkspacePermission.READ,
                handler=lambda capabilities, context, arguments: ToolOutcome(
                    payload={"accepted": True}
                ),
            )
        ],
        [ToolProfile(name="mcp", tool_names=frozenset({"strict_argument"}))],
    )
    application = _application(
        catalog,
        ToolDispatcher(catalog=catalog, executor=MinimalExecutor()),
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                content=(
                    b'{"jsonrpc":"2.0","id":"strict-argument",'
                    b'"method":"tools/call","params":{"name":"strict_argument",'
                    b'"arguments":{"value":NaN}}}'
                ),
            )

    assert "NaN" not in response.text
    result = response.json()["result"]
    assert result["isError"] is True
    error = json.loads(result["content"][0]["text"])["error"]
    assert error["code"] == "tool_arguments_invalid"
    assert error["kind"] == "invalid_argument"


@pytest.mark.asyncio
async def test_mcp_budget_matches_the_complete_unicode_call_tool_result() -> None:
    outcome = ToolOutcome(
        payload={"summary": "中文 café 🔬"},
        resource_links=(
            ToolResourceLink(
                uri="scholens://papers/11111111-1111-1111-1111-111111111111",
                name="中文论文",
                description="打开规范资源",
            ),
        ),
    )
    serialized = serialize_tool_success(outcome)
    exact_definition = ToolDefinition(
        name="exact_budget",
        description="Return a result at the exact transport budget.",
        input_model=EmptyInput,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        max_output_bytes=serialized.call_tool_result_utf8_bytes,
        handler=_unexpected_handler,
    )
    over_definition = ToolDefinition(
        name="over_budget",
        description="Return a result one byte over the transport budget.",
        input_model=EmptyInput,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        max_output_bytes=serialized.call_tool_result_utf8_bytes - 1,
        replacement_tool="exact_budget",
        handler=_unexpected_handler,
    )
    catalog = ToolCatalog(
        [exact_definition, over_definition],
        [
            ToolProfile(
                name="mcp",
                tool_names=frozenset({"exact_budget", "over_budget"}),
            )
        ],
    )
    dispatcher = RecordingDispatcher()
    dispatcher.outcome = outcome
    application = _application(catalog, dispatcher)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            exact = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "exact-budget",
                    "method": "tools/call",
                    "params": {"name": "exact_budget", "arguments": {}},
                },
            )
            over = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "over-budget",
                    "method": "tools/call",
                    "params": {"name": "over_budget", "arguments": {}},
                },
            )

    exact_result = exact.json()["result"]
    exact_bytes = len(
        json.dumps(
            exact_result,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert exact_bytes == serialized.call_tool_result_utf8_bytes
    assert "中文 café 🔬" in exact_result["content"][0]["text"]
    assert "\\u4e2d" not in exact_result["content"][0]["text"]
    assert exact_result["content"][1]["type"] == "resource_link"

    over_result = over.json()["result"]
    assert over_result["isError"] is True
    over_error = json.loads(over_result["content"][0]["text"])["error"]
    assert over_error["code"] == "tool_result_budget_exceeded"
    assert over_error["details"]["actual_output_bytes"] == exact_bytes
    assert over_error["details"]["replacement_tool"] == "exact_budget"
    assert "Use exact_budget" in over_error["remediation"]


@pytest.mark.asyncio
async def test_mcp_call_runs_through_the_shared_dispatcher() -> None:
    catalog = ToolCatalog(
        [
            ToolDefinition(
                name="who_am_i",
                description="Return the authenticated actor.",
                input_model=EmptyInput,
                execution=ToolExecutionKind.QUERY,
                required_permission=WorkspacePermission.READ,
                handler=lambda _capabilities, context, _arguments: ToolOutcome(
                    payload={"actor_id": context.actor.id}
                ),
            )
        ],
        [ToolProfile(name="mcp", tool_names=frozenset({"who_am_i"}))],
    )
    dispatcher = ToolDispatcher(catalog=catalog, executor=MinimalExecutor())
    application = _application(catalog, dispatcher)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-tool",
                    "method": "tools/call",
                    "params": {"name": "who_am_i", "arguments": {}},
                },
            )

    assert response.json()["result"]["structuredContent"]["result"] == {"actor_id": 7}
