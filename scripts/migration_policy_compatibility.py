#!/usr/bin/env python3
"""Reject mutable migration history and destructive expand revisions."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

DESTRUCTIVE_EXPAND_OPERATIONS = {
    "drop_column",
    "drop_constraint",
    "drop_index",
    "drop_table",
    "execute",
    "rename_table",
}
RESTRICTIVE_EXPAND_OPERATIONS = {
    "create_check_constraint",
    "create_exclude_constraint",
    "create_foreign_key",
    "create_primary_key",
    "create_unique_constraint",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("contract_version") != 1:
        raise ValueError(f"unsupported migration policy: {path}")
    if not isinstance(value.get("revisions"), dict):
        raise ValueError(f"migration policy has no revisions: {path}")
    return value


def _literal(tree: ast.Module, name: str, *, path: Path) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            return ast.literal_eval(value)
    raise ValueError(f"{path.name} does not define {name}")


def _expand_failures(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    failures: list[str] = []
    operation_targets = {"op"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            target = item.optional_vars
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "op"
                and call.func.attr == "batch_alter_table"
                and isinstance(target, ast.Name)
            ):
                operation_targets.add(target.id)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            not isinstance(node.func.value, ast.Name)
            or node.func.value.id not in operation_targets
        ):
            continue
        target_name = node.func.value.id
        operation = node.func.attr
        if operation in DESTRUCTIVE_EXPAND_OPERATIONS:
            failures.append(f"{path.name}:{node.lineno} uses op.{operation}")
        if operation in RESTRICTIVE_EXPAND_OPERATIONS:
            failures.append(
                f"{path.name}:{node.lineno} adds a write-restricting constraint"
            )
        if operation == "create_index":
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            unique = keywords.get("unique")
            if isinstance(unique, ast.Constant) and unique.value is True:
                failures.append(
                    f"{path.name}:{node.lineno} adds a write-restricting unique index"
                )
        column_index = 1 if target_name == "op" else 0
        if operation == "add_column" and len(node.args) > column_index:
            column = node.args[column_index]
            if isinstance(column, ast.Call):
                keywords = {keyword.arg: keyword.value for keyword in column.keywords}
                nullable = keywords.get("nullable")
                server_default = keywords.get("server_default")
                has_default = server_default is not None and not (
                    isinstance(server_default, ast.Constant)
                    and server_default.value is None
                )
                if (
                    isinstance(nullable, ast.Constant)
                    and nullable.value is False
                    and not has_default
                ):
                    failures.append(
                        f"{path.name}:{node.lineno} adds a required column without "
                        "a server default"
                    )
        if operation == "alter_column":
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            nullable = keywords.get("nullable")
            if isinstance(nullable, ast.Constant) and nullable.value is False:
                failures.append(
                    f"{path.name}:{node.lineno} makes an existing column non-nullable"
                )
            if "type_" in keywords or "new_column_name" in keywords:
                failures.append(
                    f"{path.name}:{node.lineno} changes an existing column contract"
                )
            server_default = keywords.get("server_default")
            if (
                isinstance(server_default, ast.Constant)
                and server_default.value is None
            ):
                failures.append(
                    f"{path.name}:{node.lineno} removes an existing server default"
                )
    return failures


def compatibility_failures(
    base: dict[str, Any] | None,
    revision: dict[str, Any],
    *,
    versions: Path,
) -> list[str]:
    failures: list[str] = []
    if base is not None:
        if revision.get("production_baseline_revision") != base.get(
            "production_baseline_revision"
        ):
            failures.append("production migration baseline changed")
        for name, metadata in base["revisions"].items():
            if revision["revisions"].get(name) != metadata:
                failures.append(f"migration policy rewrote existing revision {name}")
    known = set(base["revisions"]) if base is not None else set(revision["revisions"])
    paths_by_revision: dict[str, Path] = {}
    for path in versions.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        value = _literal(tree, "revision", path=path)
        if not isinstance(value, str):
            raise ValueError(f"{path.name} has an invalid revision")
        paths_by_revision[value] = path
    if set(revision["revisions"]) != set(paths_by_revision):
        failures.append("migration policy must classify every revision exactly once")
        return failures
    for name in sorted(set(revision["revisions"]).difference(known)):
        metadata = revision["revisions"][name]
        if metadata.get("phase") == "expand":
            failures.extend(_expand_failures(paths_by_revision[name]))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path)
    parser.add_argument("--revision", type=Path, required=True)
    parser.add_argument("--versions", type=Path, required=True)
    args = parser.parse_args()
    try:
        base = _load(args.base) if args.base and args.base.exists() else None
        failures = compatibility_failures(
            base,
            _load(args.revision),
            versions=args.versions,
        )
    except (OSError, SyntaxError, TypeError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"Migration policy check failed: {exc}\n")
        return 1
    if failures:
        sys.stderr.write("\n".join(failures) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
