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
)
from app.tooling.workspace import build_workspace_tool_catalog
from app.transport.mcp.server import build_mcp_transport
from httpx import ASGITransport, AsyncClient
from mcp.server.transport_security import TransportSecuritySettings
import json
import pytest
from pydantic import BaseModel, ConfigDict
from starlette.applications import Starlette
from starlette.routing import Route

ACCESS_KEY_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ACCESS_KEY_SECRET = "sk_scholens_" + "a" * 43


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[
            tuple[str, dict[str, object], ToolExecutionContext, ToolAccess]
        ] = []
        self.error: AppError | None = None

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
    assert len(tool_names) == 57
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
        def list(self, **_arguments: object) -> object:
            return SimpleNamespace(
                items=[
                    SimpleNamespace(id=project_id, title="Chain-of-thought compression")
                ]
            )

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
