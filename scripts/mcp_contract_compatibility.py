#!/usr/bin/env python3
"""Render MCP tool schemas for oasdiff and check non-schema compatibility."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("contract_version") != 1:
        raise ValueError(f"unsupported MCP contract: {path}")
    if not isinstance(value.get("tools"), dict):
        raise ValueError(f"MCP contract has no tool map: {path}")
    return value


def _schema_for_openapi(
    schema: dict[str, Any],
    *,
    prefix: str,
    components: dict[str, Any],
) -> dict[str, Any]:
    definitions = schema.get("$defs", {})
    if definitions and not isinstance(definitions, dict):
        raise ValueError("MCP JSON Schema $defs must be an object")
    names = {name: f"{prefix}_{name}" for name in definitions if isinstance(name, str)}

    def rewrite(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("#/$defs/"):
            name = value.removeprefix("#/$defs/")
            if name not in names:
                raise ValueError(f"MCP schema references an unknown definition: {name}")
            return f"#/components/schemas/{names[name]}"
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$defs":
                continue
            rewritten[key] = rewrite(item)
        return rewritten

    for name, definition in definitions.items():
        components[names[name]] = rewrite(definition)
    return rewrite(schema)


def _collect_refs(value: Any, refs: set[str]) -> None:
    """Collect every ``#/$defs/<name>`` reference inside a schema subtree."""
    if isinstance(value, str):
        if value.startswith("#/$defs/"):
            refs.add(value.removeprefix("#/$defs/"))
        return
    if isinstance(value, list):
        for item in value:
            _collect_refs(item, refs)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_refs(item, refs)


def _project_success_envelope(schema: dict[str, Any]) -> dict[str, Any]:
    """Project an MCP output schema onto its success envelope branch.

    MCP business errors are transported in the same HTTP 200 CallToolResult
    with ``isError: true``; the OpenAPI 200 projection therefore compares
    only the success envelope. The error branch stays guarded by
    ``check-metadata`` and the server conformance suite, so the HTTP-level
    diff must not treat the additive error branch as a body type change.
    Schemas without ``anyOf`` (legacy snapshots) pass through unchanged.
    """
    branches = schema.get("anyOf")
    if not isinstance(branches, list):
        return schema
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise ValueError("MCP output schema anyOf requires a $defs object")

    def resolve(branch: Any) -> dict[str, Any]:
        if not isinstance(branch, dict) or "$ref" not in branch:
            return branch
        name = branch["$ref"].removeprefix("#/$defs/")
        if name not in definitions:
            raise ValueError(
                f"MCP output schema anyOf references unknown $defs: {name}"
            )
        definition = definitions[name]
        if not isinstance(definition, dict):
            raise ValueError(f"MCP $defs/{name} is not an object schema")
        return definition

    success = None
    for branch in branches:
        resolved = resolve(branch)
        properties = resolved.get("properties")
        if isinstance(properties, dict) and "result" in properties:
            success = resolved
            break
    if success is None:
        raise ValueError("MCP output schema anyOf has no success envelope branch")

    projected = copy.deepcopy(success)
    refs: set[str] = set()
    _collect_refs(projected, refs)
    pending = list(refs)
    needed: dict[str, Any] = {}
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        definition = definitions.get(name)
        if definition is None:
            raise ValueError(f"MCP success envelope references unknown $defs: {name}")
        needed[name] = definition
        nested: set[str] = set()
        _collect_refs(definition, nested)
        for nested_name in nested:
            if nested_name not in needed:
                pending.append(nested_name)
    if needed:
        projected["$defs"] = needed
    return projected


def render_openapi(contract: dict[str, Any]) -> dict[str, Any]:
    components: dict[str, Any] = {}
    paths: dict[str, Any] = {}
    for name, raw_tool in sorted(contract["tools"].items()):
        if not isinstance(raw_tool, dict):
            raise ValueError(f"MCP tool {name} must be an object")
        input_schema = raw_tool.get("input_schema")
        output_schema = raw_tool.get("output_schema")
        if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
            raise ValueError(f"MCP tool {name} requires input and output schemas")
        output_schema = _project_success_envelope(output_schema)
        paths[f"/tools/{name}"] = {
            "post": {
                "operationId": name,
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": _schema_for_openapi(
                                input_schema,
                                prefix=f"{name}_input",
                                components=components,
                            )
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Typed MCP tool result",
                        "content": {
                            "application/json": {
                                "schema": _schema_for_openapi(
                                    output_schema,
                                    prefix=f"{name}_output",
                                    components=components,
                                )
                            }
                        },
                    }
                },
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Scholens MCP v1", "version": "1.0.0"},
        "paths": paths,
        "components": {"schemas": components},
    }


def metadata_breaks(base: dict[str, Any], revision: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for field in ("endpoint", "protocol"):
        if revision.get(field) != base.get(field):
            failures.append(f"MCP {field} changed")
    base_tools = base["tools"]
    revision_tools = revision["tools"]
    for name, old in sorted(base_tools.items()):
        new = revision_tools.get(name)
        if not isinstance(new, dict):
            failures.append(f"MCP tool removed: {name}")
            continue
        for field in ("execution", "required_permission"):
            if new.get(field) != old.get(field):
                failures.append(f"MCP tool {name} changed {field}")
        if new.get("confirmation_policy") != old.get("confirmation_policy"):
            failures.append(f"MCP tool {name} changed confirmation_policy")
        old_behavior = old.get("behavior", {})
        new_behavior = new.get("behavior", {})
        unsafe = (
            ("read_only", True, False),
            ("destructive", False, True),
            ("idempotent", True, False),
            ("open_world", False, True),
        )
        for field, safe_value, unsafe_value in unsafe:
            if (
                old_behavior.get(field) is safe_value
                and new_behavior.get(field) is unsafe_value
            ):
                failures.append(f"MCP tool {name} changed behavior.{field}")
    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render-openapi")
    render.add_argument("--contract", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    check = subparsers.add_parser("check-metadata")
    check.add_argument("--base", type=Path, required=True)
    check.add_argument("--revision", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "render-openapi":
            rendered = render_openapi(_load(args.contract))
            args.output.write_text(
                json.dumps(rendered, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            failures = metadata_breaks(_load(args.base), _load(args.revision))
            if failures:
                sys.stderr.write("\n".join(failures) + "\n")
                return 1
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"MCP compatibility check failed: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
