#!/usr/bin/env python3
"""Render MCP tool schemas for oasdiff and check non-schema compatibility."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
_MISSING = object()
_HTTP_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("contract_version") != 1:
        raise ValueError(f"unsupported MCP contract: {path}")
    if not isinstance(value.get("tools"), dict):
        raise ValueError(f"MCP contract has no tool map: {path}")
    for field in ("resources", "resource_templates"):
        if field in value and not isinstance(value[field], dict):
            raise ValueError(f"MCP contract {field} must be an object: {path}")
    return value


def _load_document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


class RestrictiveSchemaChange:
    __slots__ = (
        "boundary",
        "target",
        "schema_pointer",
        "change_kind",
        "base_value_sha256",
        "revision_value_sha256",
    )

    def __init__(
        self,
        *,
        boundary: str,
        target: str,
        schema_pointer: str,
        change_kind: str,
        base_value_sha256: str | None,
        revision_value_sha256: str,
    ) -> None:
        self.boundary = boundary
        self.target = target
        self.schema_pointer = schema_pointer
        self.change_kind = change_kind
        self.base_value_sha256 = base_value_sha256
        self.revision_value_sha256 = revision_value_sha256

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.boundary, self.target, self.schema_pointer, self.change_kind)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _resolve_pointer(document: Any, pointer: str) -> Any:
    if pointer == "#":
        return document
    if not pointer.startswith("#/"):
        raise ValueError(f"schema pointer must be a local JSON pointer: {pointer}")
    current = document
    for raw_token in pointer[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return _MISSING
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (IndexError, ValueError):
                return _MISSING
        else:
            return _MISSING
    return current


def _restriction(
    *,
    boundary: str,
    target: str,
    pointer: str,
    kind: str,
    base: Any,
    revision: Any,
) -> RestrictiveSchemaChange:
    return RestrictiveSchemaChange(
        boundary=boundary,
        target=target,
        schema_pointer=pointer,
        change_kind=kind,
        base_value_sha256=(None if base is _MISSING else _canonical_sha256(base)),
        revision_value_sha256=_canonical_sha256(revision),
    )


def _schema_restrictions(
    base: Any,
    revision: Any,
    *,
    boundary: str,
    target: str,
    pointer: str,
    base_document: dict[str, Any] | None = None,
    revision_document: dict[str, Any] | None = None,
    visited_refs: frozenset[tuple[str, str]] = frozenset(),
) -> list[RestrictiveSchemaChange]:
    """Find request restrictions that oasdiff 1.29.1 does not reliably reject.

    This is deliberately a narrow supplement to oasdiff, not a replacement
    JSON-Schema compatibility engine. Every reported correction needs an exact
    registry entry bound to its target, JSON pointer, old value, and new-value
    digest.
    """
    if not isinstance(base, dict) or not isinstance(revision, dict):
        return []
    base_ref = base.get("$ref")
    revision_ref = revision.get("$ref")
    if (
        base_document is not None
        and revision_document is not None
        and isinstance(base_ref, str)
        and isinstance(revision_ref, str)
        and base_ref.startswith("#/")
        and revision_ref.startswith("#/")
    ):
        ref_pair = (base_ref, revision_ref)
        if ref_pair in visited_refs:
            return []
        resolved_base = _resolve_pointer(base_document, base_ref)
        resolved_revision = _resolve_pointer(revision_document, revision_ref)
        if resolved_base is _MISSING or resolved_revision is _MISSING:
            raise ValueError("request schema references an unknown value")
        return _schema_restrictions(
            resolved_base,
            resolved_revision,
            boundary=boundary,
            target=target,
            pointer=revision_ref,
            base_document=base_document,
            revision_document=revision_document,
            visited_refs=visited_refs | {ref_pair},
        )
    changes: list[RestrictiveSchemaChange] = []

    for keyword, kind in (
        ("oneOf", "one_of_added"),
        ("allOf", "all_of_added"),
        ("not", "not_added"),
    ):
        if keyword not in base and keyword in revision:
            changes.append(
                _restriction(
                    boundary=boundary,
                    target=target,
                    pointer=f"{pointer}/{keyword}",
                    kind=kind,
                    base=_MISSING,
                    revision=revision[keyword],
                )
            )

    if base.get("uniqueItems") is not True and revision.get("uniqueItems") is True:
        changes.append(
            _restriction(
                boundary=boundary,
                target=target,
                pointer=f"{pointer}/uniqueItems",
                kind="unique_items_enabled",
                base=base.get("uniqueItems", _MISSING),
                revision=True,
            )
        )
    if (
        base.get("additionalProperties") is not False
        and revision.get("additionalProperties") is False
    ):
        changes.append(
            _restriction(
                boundary=boundary,
                target=target,
                pointer=f"{pointer}/additionalProperties",
                kind="additional_properties_forbidden",
                base=base.get("additionalProperties", _MISSING),
                revision=False,
            )
        )

    base_required = base.get("required")
    revision_required = revision.get("required")
    if isinstance(revision_required, list):
        old_required = set(base_required) if isinstance(base_required, list) else set()
        if any(item not in old_required for item in revision_required):
            changes.append(
                _restriction(
                    boundary=boundary,
                    target=target,
                    pointer=f"{pointer}/required",
                    kind="required_properties_added",
                    base=base.get("required", _MISSING),
                    revision=revision_required,
                )
            )

    base_enum = base.get("enum")
    revision_enum = revision.get("enum")
    if isinstance(base_enum, list) and isinstance(revision_enum, list):
        revision_values = {_canonical_sha256(item) for item in revision_enum}
        if any(_canonical_sha256(item) not in revision_values for item in base_enum):
            changes.append(
                _restriction(
                    boundary=boundary,
                    target=target,
                    pointer=f"{pointer}/enum",
                    kind="enum_values_removed",
                    base=base_enum,
                    revision=revision_enum,
                )
            )

    for keyword, kind in (("const", "const_changed"), ("pattern", "pattern_changed")):
        if keyword in revision and base.get(keyword, _MISSING) != revision[keyword]:
            changes.append(
                _restriction(
                    boundary=boundary,
                    target=target,
                    pointer=f"{pointer}/{keyword}",
                    kind=kind,
                    base=base.get(keyword, _MISSING),
                    revision=revision[keyword],
                )
            )

    for keyword in (
        "minimum",
        "exclusiveMinimum",
        "minLength",
        "minItems",
        "minProperties",
        "minContains",
    ):
        old = base.get(keyword)
        new = revision.get(keyword)
        if isinstance(new, (int, float)) and (
            not isinstance(old, (int, float)) or new > old
        ):
            changes.append(
                _restriction(
                    boundary=boundary,
                    target=target,
                    pointer=f"{pointer}/{keyword}",
                    kind=f"{keyword}_increased",
                    base=base.get(keyword, _MISSING),
                    revision=new,
                )
            )
    for keyword in (
        "maximum",
        "exclusiveMaximum",
        "maxLength",
        "maxItems",
        "maxProperties",
        "maxContains",
    ):
        old = base.get(keyword)
        new = revision.get(keyword)
        if isinstance(new, (int, float)) and (
            not isinstance(old, (int, float)) or new < old
        ):
            changes.append(
                _restriction(
                    boundary=boundary,
                    target=target,
                    pointer=f"{pointer}/{keyword}",
                    kind=f"{keyword}_decreased",
                    base=base.get(keyword, _MISSING),
                    revision=new,
                )
            )

    for container in ("properties", "$defs", "dependentSchemas"):
        old_children = base.get(container)
        new_children = revision.get(container)
        if not isinstance(old_children, dict) or not isinstance(new_children, dict):
            continue
        for name in old_children.keys() & new_children.keys():
            changes.extend(
                _schema_restrictions(
                    old_children[name],
                    new_children[name],
                    boundary=boundary,
                    target=target,
                    pointer=(f"{pointer}/{container}/{_pointer_token(str(name))}"),
                    base_document=base_document,
                    revision_document=revision_document,
                    visited_refs=visited_refs,
                )
            )
    if "items" in base and "items" in revision:
        changes.extend(
            _schema_restrictions(
                base["items"],
                revision["items"],
                boundary=boundary,
                target=target,
                pointer=f"{pointer}/items",
                base_document=base_document,
                revision_document=revision_document,
                visited_refs=visited_refs,
            )
        )
    for container in ("allOf", "anyOf", "oneOf", "prefixItems"):
        old_children = base.get(container)
        new_children = revision.get(container)
        if not isinstance(old_children, list) or not isinstance(new_children, list):
            continue
        for index, (old_child, new_child) in enumerate(
            zip(old_children, new_children, strict=False)
        ):
            changes.extend(
                _schema_restrictions(
                    old_child,
                    new_child,
                    boundary=boundary,
                    target=target,
                    pointer=f"{pointer}/{container}/{index}",
                    base_document=base_document,
                    revision_document=revision_document,
                    visited_refs=visited_refs,
                )
            )
    return changes


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
    for collection, path_kind in (
        ("resources", "static"),
        ("resource_templates", "template"),
    ):
        for uri, raw_resource in sorted(contract.get(collection, {}).items()):
            if not isinstance(raw_resource, dict):
                raise ValueError(f"MCP {collection} entry {uri} must be an object")
            name = raw_resource.get("name")
            output_schema = raw_resource.get("output_schema")
            if not isinstance(name, str) or not isinstance(output_schema, dict):
                raise ValueError(
                    f"MCP {collection} entry {uri} requires name and output_schema"
                )
            prefix = f"resource_{path_kind}_{name}".replace("-", "_")
            paths[f"/resources/{path_kind}/{name}"] = {
                "get": {
                    "operationId": prefix,
                    "responses": {
                        "200": {
                            "description": "Typed MCP resource result",
                            "content": {
                                raw_resource.get("mime_type", "application/json"): {
                                    "schema": _schema_for_openapi(
                                        output_schema,
                                        prefix=f"{prefix}_output",
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
    old_result_limits = base.get("tool_result_limits")
    if isinstance(old_result_limits, dict) and (
        revision.get("tool_result_limits") != old_result_limits
    ):
        failures.append("MCP tool result budget scope changed")
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
        old_budget = old.get("max_success_envelope_utf8_bytes")
        new_budget = new.get("max_success_envelope_utf8_bytes")
        if isinstance(old_budget, int) and (
            not isinstance(new_budget, int) or new_budget < old_budget
        ):
            failures.append(f"MCP tool {name} decreased output byte budget")
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
    old_limit = base.get("resource_limits", {}).get("max_utf8_bytes")
    new_limit = revision.get("resource_limits", {}).get("max_utf8_bytes")
    if isinstance(old_limit, int) and (
        not isinstance(new_limit, int) or new_limit < old_limit
    ):
        failures.append("MCP resource max_utf8_bytes decreased")
    for collection, label in (
        ("resources", "resource"),
        ("resource_templates", "resource template"),
    ):
        old_entries = base.get(collection, {})
        new_entries = revision.get(collection, {})
        if not isinstance(old_entries, dict) or not isinstance(new_entries, dict):
            continue
        for uri, old in sorted(old_entries.items()):
            new = new_entries.get(uri)
            if not isinstance(new, dict):
                failures.append(f"MCP {label} removed: {uri}")
                continue
            if not isinstance(old, dict):
                continue
            for field in ("name", "mime_type"):
                if new.get(field) != old.get(field):
                    failures.append(f"MCP {label} {uri} changed {field}")
    return failures


def _resolved_request_schema(
    document: dict[str, Any], schema: Any, inline_pointer: str
) -> tuple[str, Any] | None:
    if not isinstance(schema, dict):
        return None
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/"):
        resolved = _resolve_pointer(document, reference)
        if resolved is _MISSING:
            raise ValueError(f"request schema references an unknown value: {reference}")
        return reference, resolved
    return inline_pointer, schema


def _mcp_request_restrictions(
    base: dict[str, Any], revision: dict[str, Any]
) -> list[RestrictiveSchemaChange]:
    changes: list[RestrictiveSchemaChange] = []
    for name, old_tool in base["tools"].items():
        new_tool = revision["tools"].get(name)
        if not isinstance(old_tool, dict) or not isinstance(new_tool, dict):
            continue
        old_schema = old_tool.get("input_schema")
        new_schema = new_tool.get("input_schema")
        if not isinstance(old_schema, dict) or not isinstance(new_schema, dict):
            continue
        pointer = f"#/tools/{_pointer_token(name)}/input_schema"
        changes.extend(
            _schema_restrictions(
                old_schema,
                new_schema,
                boundary="mcp",
                target=name,
                pointer=pointer,
            )
        )
    return changes


def _http_request_restrictions(
    base: dict[str, Any], revision: dict[str, Any]
) -> list[RestrictiveSchemaChange]:
    changes: list[RestrictiveSchemaChange] = []
    base_paths = base.get("paths", {})
    revision_paths = revision.get("paths", {})
    if not isinstance(base_paths, dict) or not isinstance(revision_paths, dict):
        raise ValueError("OpenAPI paths must be objects")
    for path, old_path_item in base_paths.items():
        new_path_item = revision_paths.get(path)
        if not isinstance(old_path_item, dict) or not isinstance(new_path_item, dict):
            continue
        for method in _HTTP_METHODS & old_path_item.keys() & new_path_item.keys():
            old_operation = old_path_item[method]
            new_operation = new_path_item[method]
            if not isinstance(old_operation, dict) or not isinstance(
                new_operation, dict
            ):
                continue
            old_content = old_operation.get("requestBody", {}).get("content", {})
            new_content = new_operation.get("requestBody", {}).get("content", {})
            if not isinstance(old_content, dict) or not isinstance(new_content, dict):
                continue
            target = f"{method.upper()} {path}"
            for media_type in old_content.keys() & new_content.keys():
                old_media = old_content[media_type]
                new_media = new_content[media_type]
                if not isinstance(old_media, dict) or not isinstance(new_media, dict):
                    continue
                inline_pointer = (
                    f"#/paths/{_pointer_token(path)}/{method}/requestBody/content/"
                    f"{_pointer_token(media_type)}/schema"
                )
                old_root = _resolved_request_schema(
                    base, old_media.get("schema"), inline_pointer
                )
                new_root = _resolved_request_schema(
                    revision, new_media.get("schema"), inline_pointer
                )
                if old_root is None or new_root is None:
                    continue
                _old_pointer, old_schema = old_root
                new_pointer, new_schema = new_root
                changes.extend(
                    _schema_restrictions(
                        old_schema,
                        new_schema,
                        boundary="http",
                        target=target,
                        pointer=new_pointer,
                        base_document=base,
                        revision_document=revision,
                    )
                )
    return changes


def _assign_pointer(document: dict[str, Any], pointer: str, value: Any) -> None:
    if not pointer.startswith("#/"):
        raise ValueError(f"schema pointer must be a local JSON pointer: {pointer}")
    tokens = [
        token.replace("~1", "/").replace("~0", "~") for token in pointer[2:].split("/")
    ]
    current: Any = document
    for token in tokens[:-1]:
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (IndexError, ValueError) as exc:
                raise ValueError(
                    f"schema pointer has an unknown parent: {pointer}"
                ) from exc
        else:
            raise ValueError(f"schema pointer has an unknown parent: {pointer}")
    leaf = tokens[-1]
    if isinstance(current, dict):
        current[leaf] = copy.deepcopy(value)
        return
    if isinstance(current, list):
        try:
            current[int(leaf)] = copy.deepcopy(value)
            return
        except (IndexError, ValueError) as exc:
            raise ValueError(f"schema pointer has an unknown leaf: {pointer}") from exc
    raise ValueError(f"schema pointer has an unknown parent: {pointer}")


def prepare_schema_correction_bases(
    *,
    registry: dict[str, Any],
    base_mcp: dict[str, Any],
    revision_mcp: dict[str, Any],
    base_http: dict[str, Any],
    revision_http: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project verified schema corrections onto temporary comparison bases."""

    failures = correction_registry_failures(registry)
    if failures:
        raise ValueError("; ".join(failures))
    revisions = {"mcp": revision_mcp, "http": revision_http}
    prepared = {"mcp": copy.deepcopy(base_mcp), "http": copy.deepcopy(base_http)}
    corrections = {
        (
            entry["boundary"],
            entry["target"],
            entry["schema_pointer"],
            entry["change_kind"],
        ): entry
        for entry in registry["entries"]
    }
    active_changes = [
        *_mcp_request_restrictions(base_mcp, revision_mcp),
        *_http_request_restrictions(base_http, revision_http),
    ]
    assignments: dict[tuple[str, str], tuple[str, Any]] = {}
    for change in active_changes:
        entry = corrections.get(change.key)
        label = (
            f"{change.boundary} {change.target} {change.schema_pointer} "
            f"({change.change_kind})"
        )
        if entry is None:
            raise ValueError(f"unregistered restrictive request schema change: {label}")
        if entry["base_value_sha256"] != change.base_value_sha256:
            raise ValueError(f"schema correction base digest mismatch: {label}")
        if entry["revision_value_sha256"] != change.revision_value_sha256:
            raise ValueError(f"schema correction revision digest mismatch: {label}")
        boundary = change.boundary
        pointer = change.schema_pointer
        revision_value = _resolve_pointer(revisions[boundary], pointer)
        if revision_value is _MISSING:
            raise ValueError(
                f"schema correction revision pointer is missing: {boundary} {pointer}"
            )
        revision_digest = _canonical_sha256(revision_value)
        key = (boundary, pointer)
        prior = assignments.get(key)
        if prior is not None and prior[0] != revision_digest:
            raise ValueError(f"conflicting schema corrections: {boundary} {pointer}")
        assignments[key] = (revision_digest, revision_value)
    for (boundary, pointer), (_digest, value) in assignments.items():
        _assign_pointer(prepared[boundary], pointer, value)
    return prepared["mcp"], prepared["http"]


_CORRECTION_FIELDS = {
    "id",
    "boundary",
    "target",
    "schema_pointer",
    "change_kind",
    "base_value_sha256",
    "revision_value_sha256",
    "owner",
    "recorded_on",
    "reason",
    "runtime_evidence",
}


def correction_registry_failures(registry: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if set(registry) != {"contract_version", "entries"}:
        failures.append("schema correction registry has unsupported top-level fields")
    if registry.get("contract_version") != 1:
        failures.append(
            "schema correction registry has an unsupported contract version"
        )
    entries = registry.get("entries")
    if not isinstance(entries, list):
        return [*failures, "schema correction registry entries must be a list"]
    identifiers: set[str] = set()
    keys: set[tuple[object, ...]] = set()
    for index, entry in enumerate(entries):
        label = f"schema correction entry {index}"
        if not isinstance(entry, dict):
            failures.append(f"{label} must be an object")
            continue
        if set(entry) != _CORRECTION_FIELDS:
            failures.append(f"{label} has unsupported fields")
            continue
        identifier = entry["id"]
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier
        ):
            failures.append(f"{label} has an invalid id")
        elif identifier in identifiers:
            failures.append(f"duplicate schema correction id: {identifier}")
        else:
            identifiers.add(identifier)
        if entry["boundary"] not in {"http", "mcp"}:
            failures.append(f"{label} has an invalid boundary")
        for field in (
            "target",
            "schema_pointer",
            "change_kind",
            "owner",
            "recorded_on",
            "reason",
            "runtime_evidence",
        ):
            if not isinstance(entry[field], str) or not entry[field].strip():
                failures.append(f"{label} has an invalid {field}")
        if isinstance(entry["schema_pointer"], str):
            try:
                _resolve_pointer({}, entry["schema_pointer"])
            except ValueError:
                failures.append(f"{label} has an invalid schema_pointer")
        for field in ("base_value_sha256", "revision_value_sha256"):
            value = entry[field]
            if value is not None and (
                not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None
            ):
                failures.append(f"{label} has an invalid {field}")
        if entry["revision_value_sha256"] is None:
            failures.append(f"{label} has an invalid revision_value_sha256")
        if (
            not isinstance(entry["recorded_on"], str)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["recorded_on"]) is None
        ):
            failures.append(f"{label} has an invalid recorded_on")
        evidence = entry["runtime_evidence"]
        if not _runtime_evidence_exists(evidence):
            failures.append(f"{label} has unverifiable runtime_evidence")
        key = tuple(
            entry.get(field)
            for field in (
                "boundary",
                "target",
                "schema_pointer",
                "change_kind",
            )
        )
        if key in keys:
            failures.append(f"duplicate schema correction target: {identifier}")
        keys.add(key)
    return failures


def _runtime_evidence_exists(value: object) -> bool:
    """Verify one exact top-level pytest node without importing product code.

    The full Server lane executes every referenced test. This dependency-free
    structural check is used by the public-contract lane to ensure a registry
    entry cannot pass merely because its claimed node is a substring in an
    unrelated file or comment.
    """

    if not isinstance(value, str) or value.count("::") != 1:
        return False
    relative_path, node = value.split("::", 1)
    if not re.fullmatch(
        r"server/tests/[A-Za-z0-9_./-]+\.py", relative_path
    ) or not re.fullmatch(r"test_[A-Za-z0-9_]+", node):
        return False
    evidence_path = (ROOT / relative_path).resolve()
    tests_root = (ROOT / "server/tests").resolve()
    if tests_root not in evidence_path.parents or not evidence_path.is_file():
        return False
    try:
        module = ast.parse(evidence_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return False
    return any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == node
        for statement in module.body
    )


def schema_correction_failures(
    *,
    base_registry: dict[str, Any],
    registry: dict[str, Any],
    base_mcp: dict[str, Any],
    revision_mcp: dict[str, Any],
    base_http: dict[str, Any],
    revision_http: dict[str, Any],
) -> list[str]:
    failures = correction_registry_failures(registry)
    failures.extend(
        f"base {failure}" for failure in correction_registry_failures(base_registry)
    )
    if failures:
        return failures

    base_by_id = {entry["id"]: entry for entry in base_registry["entries"]}
    revision_by_id = {entry["id"]: entry for entry in registry["entries"]}
    for identifier, old in base_by_id.items():
        new = revision_by_id.get(identifier)
        if new is None:
            failures.append(f"schema correction tombstone removed: {identifier}")
        elif new != old:
            failures.append(
                f"schema correction changed after registration: {identifier}"
            )

    changes = [
        *_mcp_request_restrictions(base_mcp, revision_mcp),
        *_http_request_restrictions(base_http, revision_http),
    ]
    corrections = {
        (
            entry["boundary"],
            entry["target"],
            entry["schema_pointer"],
            entry["change_kind"],
        ): entry
        for entry in registry["entries"]
    }
    active_keys = {change.key for change in changes}
    for change in changes:
        entry = corrections.get(change.key)
        label = (
            f"{change.boundary} {change.target} {change.schema_pointer} "
            f"({change.change_kind})"
        )
        if entry is None:
            failures.append(f"unregistered restrictive request schema change: {label}")
            continue
        if entry["base_value_sha256"] != change.base_value_sha256:
            failures.append(f"schema correction base digest mismatch: {label}")
        if entry["revision_value_sha256"] != change.revision_value_sha256:
            failures.append(f"schema correction revision digest mismatch: {label}")
    for identifier, entry in revision_by_id.items():
        if identifier in base_by_id:
            continue
        key = tuple(
            entry[field]
            for field in (
                "boundary",
                "target",
                "schema_pointer",
                "change_kind",
            )
        )
        if key not in active_keys:
            failures.append(
                f"new schema correction does not match the current transition: {identifier}"
            )
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
    corrections = subparsers.add_parser("check-schema-corrections")
    corrections.add_argument("--base-registry", type=Path, required=True)
    corrections.add_argument("--registry", type=Path, required=True)
    corrections.add_argument("--base-mcp", type=Path, required=True)
    corrections.add_argument("--revision-mcp", type=Path, required=True)
    corrections.add_argument("--base-http", type=Path, required=True)
    corrections.add_argument("--revision-http", type=Path, required=True)
    prepare = subparsers.add_parser("prepare-schema-correction-bases")
    prepare.add_argument("--registry", type=Path, required=True)
    prepare.add_argument("--base-mcp", type=Path, required=True)
    prepare.add_argument("--revision-mcp", type=Path, required=True)
    prepare.add_argument("--base-http", type=Path, required=True)
    prepare.add_argument("--revision-http", type=Path, required=True)
    prepare.add_argument("--output-mcp", type=Path, required=True)
    prepare.add_argument("--output-http", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "render-openapi":
            rendered = render_openapi(_load(args.contract))
            args.output.write_text(
                json.dumps(
                    rendered,
                    allow_nan=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        elif args.command == "check-metadata":
            failures = metadata_breaks(_load(args.base), _load(args.revision))
            if failures:
                sys.stderr.write("\n".join(failures) + "\n")
                return 1
        elif args.command == "check-schema-corrections":
            failures = schema_correction_failures(
                base_registry=_load_document(args.base_registry),
                registry=_load_document(args.registry),
                base_mcp=_load(args.base_mcp),
                revision_mcp=_load(args.revision_mcp),
                base_http=_load_document(args.base_http),
                revision_http=_load_document(args.revision_http),
            )
            if failures:
                sys.stderr.write("\n".join(failures) + "\n")
                return 1
        else:
            prepared_mcp, prepared_http = prepare_schema_correction_bases(
                registry=_load_document(args.registry),
                base_mcp=_load(args.base_mcp),
                revision_mcp=_load(args.revision_mcp),
                base_http=_load_document(args.base_http),
                revision_http=_load_document(args.revision_http),
            )
            for path, document in (
                (args.output_mcp, prepared_mcp),
                (args.output_http, prepared_http),
            ):
                path.write_text(
                    json.dumps(
                        document,
                        allow_nan=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"MCP compatibility check failed: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
