"""Deterministic public MCP tool-contract artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.shared.domain import WorkspacePermission
from app.tooling import ToolAccess
from app.tooling.workspace import MCP_TOOL_PROFILE, build_workspace_tool_catalog
from app.transport.mcp.server import tool_output_schema

SERVER_ROOT = Path(__file__).resolve().parents[3]
OUTPUT = SERVER_ROOT / "contracts/mcp-v1.json"


def public_mcp_contract() -> dict[str, object]:
    """Return the complete v1 catalog independent of one key's permissions."""
    catalog = build_workspace_tool_catalog(
        ingestion=cast(PaperIngestionWorkflow, object()),
        citations=cast(CitationWorkflow, object()),
    )
    access = ToolAccess(
        profile_name=MCP_TOOL_PROFILE,
        permissions=frozenset(WorkspacePermission),
    )
    tools: dict[str, object] = {}
    for definition in catalog.definitions_for(access):
        behavior = definition.behavior
        if behavior is None or definition.output_model is None:
            raise ValueError(f"MCP tool {definition.name} is missing public metadata")
        tools[definition.name] = {
            "title": definition.title,
            "description": definition.description,
            "input_schema": definition.input_model.model_json_schema(),
            "output_schema": tool_output_schema(definition.output_model),
            # Async reads remain public queries; scheduling is an internal runtime detail.
            "execution": (
                "query" if behavior.read_only else definition.execution.value
            ),
            "required_permission": definition.required_permission.value,
            "confirmation_policy": definition.confirmation_policy.value,
            "behavior": {
                "read_only": behavior.read_only,
                "destructive": behavior.destructive,
                "idempotent": behavior.idempotent,
                "open_world": behavior.open_world,
            },
        }
    return {
        "contract_version": 1,
        "endpoint": "/mcp",
        "protocol": "mcp",
        "server": {"name": "scholens", "version": "1.0.0"},
        "tools": tools,
    }


def encoded_artifact() -> str:
    return json.dumps(public_mcp_contract(), indent=2, sort_keys=True) + "\n"


def check_contract() -> tuple[Path, ...]:
    expected = encoded_artifact()
    if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
        return (OUTPUT,)
    return ()


def export_contract() -> tuple[Path, ...]:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(encoded_artifact(), encoding="utf-8")
    return (OUTPUT,)


__all__ = ["OUTPUT", "check_contract", "export_contract", "public_mcp_contract"]
