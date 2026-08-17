#!/usr/bin/env python3
"""Validate owned, time-bounded public compatibility entries."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

BOUNDARIES = {"http", "mcp", "job", "persistence"}
ENTRY_KEYS = {
    "id",
    "boundary",
    "target",
    "owner",
    "replacement",
    "deprecated_on",
    "earliest_removal_on",
    "telemetry_key",
    "zero_traffic_since",
    "state",
    "removed_on",
    "removal_evidence",
}
IDENTIFIER = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
HTTP_TARGET = re.compile(r"(GET|POST|PUT|PATCH|DELETE) (/api/v1(?:/[^ ]*)?)")
MUTABLE_DEPRECATION_FIELDS = {
    "zero_traffic_since",
    "state",
    "removed_on",
    "removal_evidence",
}


def validation_failures(
    registry: object,
    *,
    today: date | None = None,
) -> list[str]:
    if not isinstance(registry, dict) or registry.get("contract_version") != 1:
        return ["deprecation registry has an unsupported contract version"]
    if set(registry) != {"contract_version", "entries"}:
        return ["deprecation registry has unsupported top-level fields"]
    entries = registry.get("entries")
    if not isinstance(entries, list):
        return ["deprecation registry entries must be a list"]
    failures: list[str] = []
    identifiers: set[str] = set()
    telemetry_keys: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"deprecation entry {index}"
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            failures.append(f"{label} must contain exactly the required fields")
            continue
        identifier = entry["id"]
        telemetry_key = entry["telemetry_key"]
        for field in ("id", "target", "owner", "replacement", "telemetry_key"):
            if not isinstance(entry[field], str) or not entry[field].strip():
                failures.append(f"{label} has an invalid {field}")
        if isinstance(identifier, str):
            if IDENTIFIER.fullmatch(identifier) is None:
                failures.append(f"{label} has a non-canonical id")
            if identifier in identifiers:
                failures.append(f"duplicate deprecation id: {identifier}")
            identifiers.add(identifier)
        if entry["boundary"] not in BOUNDARIES:
            failures.append(f"{label} has an invalid boundary")
        elif entry["boundary"] == "http" and (
            not isinstance(entry["target"], str)
            or HTTP_TARGET.fullmatch(entry["target"]) is None
        ):
            failures.append(f"{label} has an invalid HTTP target")
        elif entry["boundary"] == "mcp" and (
            not isinstance(entry["target"], str)
            or IDENTIFIER.fullmatch(entry["target"]) is None
        ):
            failures.append(f"{label} has an invalid MCP target")
        if isinstance(telemetry_key, str):
            if IDENTIFIER.fullmatch(telemetry_key) is None:
                failures.append(f"{label} has a non-canonical telemetry_key")
            if telemetry_key in telemetry_keys:
                failures.append(f"duplicate deprecation telemetry_key: {telemetry_key}")
            telemetry_keys.add(telemetry_key)
        try:
            deprecated_on = date.fromisoformat(entry["deprecated_on"])
            earliest_removal_on = date.fromisoformat(entry["earliest_removal_on"])
            zero_traffic_since: date | None = (
                date.fromisoformat(entry["zero_traffic_since"])
                if entry["zero_traffic_since"] is not None
                else None
            )
        except (TypeError, ValueError):
            failures.append(f"{label} has an invalid ISO date")
            continue
        if (earliest_removal_on - deprecated_on).days < 90:
            failures.append(f"{label} has a deprecation window shorter than 90 days")
        if zero_traffic_since is not None and zero_traffic_since < deprecated_on:
            failures.append(f"{label} has zero traffic before its deprecation date")
        state = entry["state"]
        removed_on_value = entry["removed_on"]
        evidence = entry["removal_evidence"]
        if state == "deprecated":
            if removed_on_value is not None or evidence is not None:
                failures.append(f"{label} records removal evidence before removal")
        elif state == "removed":
            try:
                removed_on = date.fromisoformat(removed_on_value)
            except (TypeError, ValueError):
                failures.append(f"{label} has an invalid removal date")
                continue
            if not isinstance(evidence, str) or not evidence.strip():
                failures.append(f"{label} has no removal evidence")
            if zero_traffic_since is None:
                failures.append(f"{label} has no zero-traffic start date")
            else:
                if removed_on < zero_traffic_since + timedelta(days=30):
                    failures.append(
                        f"{label} has fewer than 30 consecutive zero-traffic days"
                    )
            if removed_on < earliest_removal_on:
                failures.append(f"{label} was removed before its 90-day window")
            if removed_on > (today or date.today()):
                failures.append(f"{label} has a future removal date")
        else:
            failures.append(f"{label} has an invalid state")
    return failures


def _removed_targets(registry: dict[str, Any], *, boundary: str) -> set[str]:
    failures = validation_failures(registry)
    if failures:
        raise ValueError("; ".join(failures))
    return {
        entry["target"]
        for entry in registry["entries"]
        if entry["boundary"] == boundary and entry["state"] == "removed"
    }


def transition_failures(
    base: object,
    revision: object,
    *,
    today: date | None = None,
) -> list[str]:
    failures = [
        *(f"base: {failure}" for failure in validation_failures(base, today=today)),
        *(
            f"revision: {failure}"
            for failure in validation_failures(revision, today=today)
        ),
    ]
    if failures or not isinstance(base, dict) or not isinstance(revision, dict):
        return failures
    base_entries = {entry["id"]: entry for entry in base["entries"]}
    revision_entries = {entry["id"]: entry for entry in revision["entries"]}
    for identifier, old in base_entries.items():
        new = revision_entries.get(identifier)
        if new is None:
            failures.append(f"deprecation tombstone removed: {identifier}")
            continue
        for field in ENTRY_KEYS.difference(MUTABLE_DEPRECATION_FIELDS):
            if new[field] != old[field]:
                failures.append(f"deprecation {identifier} changed immutable {field}")
        if old["state"] == "removed" and new != old:
            failures.append(f"removed deprecation tombstone changed: {identifier}")
        if old["state"] == "deprecated" and new["state"] == "removed":
            if old["zero_traffic_since"] is None:
                failures.append(
                    f"deprecation {identifier} must record zero traffic before removal"
                )
            elif new["zero_traffic_since"] != old["zero_traffic_since"]:
                failures.append(
                    f"deprecation {identifier} changed zero-traffic evidence during removal"
                )
    for identifier, entry in revision_entries.items():
        if identifier not in base_entries and entry["state"] != "deprecated":
            failures.append(f"new deprecation must start as deprecated: {identifier}")
    return failures


def prepare_http_base(
    base: dict[str, Any],
    revision: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    prepared = copy.deepcopy(base)
    for target in sorted(_removed_targets(registry, boundary="http")):
        match = HTTP_TARGET.fullmatch(target)
        if match is None:
            raise ValueError(f"invalid retired HTTP target: {target}")
        method, path = match.groups()
        operation = method.lower()
        if operation in revision.get("paths", {}).get(path, {}):
            raise ValueError(f"retired HTTP target still exists: {target}")
        path_item = prepared.get("paths", {}).get(path)
        if not isinstance(path_item, dict) or operation not in path_item:
            continue
        del path_item[operation]
        if not any(
            key in {"get", "post", "put", "patch", "delete"} for key in path_item
        ):
            del prepared["paths"][path]
    return prepared


def prepare_mcp_base(
    base: dict[str, Any],
    revision: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    prepared = copy.deepcopy(base)
    for target in sorted(_removed_targets(registry, boundary="mcp")):
        if target in revision.get("tools", {}):
            raise ValueError(f"retired MCP target still exists: {target}")
        prepared.get("tools", {}).pop(target, None)
    return prepared


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--registry", type=Path, required=True)
    transition = subparsers.add_parser("check-transition")
    transition.add_argument("--base", type=Path, required=True)
    transition.add_argument("--revision", type=Path, required=True)
    for name in ("prepare-http-base", "prepare-mcp-base"):
        prepare = subparsers.add_parser(name)
        prepare.add_argument("--registry", type=Path, required=True)
        prepare.add_argument("--base", type=Path, required=True)
        prepare.add_argument("--revision", type=Path, required=True)
        prepare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "check":
            registry = _load(args.registry)
            failures = validation_failures(registry)
        elif args.command == "check-transition":
            failures = transition_failures(_load(args.base), _load(args.revision))
        else:
            registry = _load(args.registry)
            base = _load(args.base)
            revision = _load(args.revision)
            prepared = (
                prepare_http_base(base, revision, registry)
                if args.command == "prepare-http-base"
                else prepare_mcp_base(base, revision, registry)
            )
            args.output.write_text(
                json.dumps(prepared, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            failures = []
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"Deprecation registry check failed: {exc}\n")
        return 1
    if failures:
        sys.stderr.write("\n".join(failures) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
