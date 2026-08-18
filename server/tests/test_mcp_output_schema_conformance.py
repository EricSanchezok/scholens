"""Every advertised MCP tool output schema must accept both the success
envelope and the structured error envelope.

Strict MCP clients (for example the TypeScript SDK with ajv) validate
``structuredContent`` against the tool's advertised ``outputSchema`` and
reject any response that does not match. Before the error envelope was part
of the advertised schema, every business error produced ``-32602`` on the
client ("Structured content does not match the tool's output schema: data
must have required property 'result'") which hid the real error code and
message. These tests pin the fix: the schema must keep the strict success
branch unchanged and add an error branch that the real error serialization
always satisfies.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, cast

import jsonschema
import pytest
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.shared.application import ErrorEnvelope
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.tooling import ToolAccess
from app.tooling.workspace import MCP_TOOL_PROFILE, build_workspace_tool_catalog
from app.transport.mcp.server import _error_remediation, tool_output_schema
from httpx import ASGITransport, AsyncClient
from tests.test_mcp_transport import (
    _initialize,
    _transport,
)


def _catalog_tools() -> list[Any]:
    catalog = build_workspace_tool_catalog(
        ingestion=cast(PaperIngestionWorkflow, object()),
        citations=cast(CitationWorkflow, object()),
    )
    access = ToolAccess(
        profile_name=MCP_TOOL_PROFILE,
        permissions=frozenset(WorkspacePermission),
    )
    return [
        definition
        for definition in catalog.definitions_for(access)
        if definition.output_model is not None
    ]


def _resolve_branches(schema: dict[str, object]) -> list[dict[str, object]]:
    """Resolve the two advertised envelope branches (anyOf with $ref or inline)."""
    any_of = schema.get("anyOf")
    assert isinstance(any_of, list) and len(any_of) == 2, (
        f"output schema must advertise exactly two branches, got {any_of!r}"
    )
    definitions = schema.get("$defs", {})
    assert isinstance(definitions, dict)
    resolved: list[dict[str, object]] = []
    for branch in any_of:
        ref = branch.get("$ref") if isinstance(branch, dict) else None
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            resolved.append(cast(dict[str, object], definitions[name]))
        else:
            resolved.append(cast(dict[str, object], branch))
    return resolved


def _error_sample(
    *,
    code: str = "project_access_denied",
    kind: FailureKind = FailureKind.PERMISSION_DENIED,
) -> dict[str, object]:
    """The exact shape `_error_result` serializes into structuredContent."""
    error = ErrorEnvelope.from_app_error(
        AppError(kind=kind, code=code, message="Access denied"),
        stage="mcp_tool_call",
        request_id=None,
        correlation_id=None,
        diagnostic_id=None,
    ).to_dict()
    error["remediation"] = _error_remediation(kind=kind, code=code)
    return {"error": error}


def _validator(schema: dict[str, object]) -> jsonschema.Draft202012Validator:
    format_checker = jsonschema.FormatChecker()
    rfc3339_datetime = re.compile(
        r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
        r"(?:[Zz]|[+-]\d{2}:\d{2})$"
    )

    def strict_datetime(value: object) -> bool:
        if not isinstance(value, str) or rfc3339_datetime.fullmatch(value) is None:
            return False
        normalized = value[:-1] + "+00:00" if value[-1:] in {"Z", "z"} else value
        try:
            return datetime.fromisoformat(normalized).tzinfo is not None
        except ValueError:
            return False

    format_checker.checks("date-time")(strict_datetime)
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=format_checker,
    )


def test_schema_validator_matches_ajv_timezone_requirement() -> None:
    schema: dict[str, object] = {"type": "string", "format": "date-time"}

    assert list(_validator(schema).iter_errors("2017-01-01T00:00:00"))
    assert not list(_validator(schema).iter_errors("2017-01-01T00:00:00Z"))


def test_catalog_has_56_tools_with_output_models() -> None:
    assert len(_catalog_tools()) == 56


def test_every_tool_output_schema_accepts_the_error_envelope() -> None:
    for definition in _catalog_tools():
        schema = tool_output_schema(definition.output_model)
        errors = list(_validator(schema).iter_errors(_error_sample()))
        assert not errors, (
            f"{definition.name} rejects its error envelope: "
            f"{[error.message for error in errors]}"
        )


def test_every_tool_output_schema_keeps_the_strict_success_branch() -> None:
    for definition in _catalog_tools():
        schema = tool_output_schema(definition.output_model)
        success_branch, error_branch = _resolve_branches(schema)
        success_properties = success_branch.get("properties", {})
        assert "result" in success_branch.get("required", []), (
            f"{definition.name} success branch no longer requires result"
        )
        assert "result" in success_properties, (
            f"{definition.name} success branch no longer declares result"
        )
        assert "error" not in success_properties
        error_properties = error_branch.get("properties", {})
        assert "error" in error_branch.get("required", []), (
            f"{definition.name} error branch does not require error"
        )
        assert isinstance(error_properties.get("error"), dict), (
            f"{definition.name} error branch does not declare an error object"
        )


@pytest.mark.asyncio
async def test_error_response_passes_the_advertised_output_schema_end_to_end() -> None:
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
                        "arguments": {},
                    },
                },
            )

    tools = listed.json()["result"]["tools"]
    schema = next(
        tool["outputSchema"] for tool in tools if tool["name"] == "list_projects"
    )
    structured = called.json()["result"]["structuredContent"]
    assert called.json()["result"]["isError"] is True
    errors = list(_validator(schema).iter_errors(structured))
    assert not errors, [error.message for error in errors]
