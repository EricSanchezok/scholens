#!/usr/bin/env python3
"""Validate Scholens shared Python package and consumer contracts.

This checker uses only the Python standard library. It does not install
dependencies, update lockfiles, start services, or mutate the workspace.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = ROOT / "packages"
EXPECTED_PYTHON = ">=3.12"
FORBIDDEN_APPLICATION_IMPORTS = {"app", "jobs", "server", "src"}


@dataclass(frozen=True, slots=True)
class PackageSpec:
    directory: str
    distribution: str
    import_name: str

    @property
    def root(self) -> Path:
        return PACKAGES_ROOT / self.directory


PACKAGE_SPECS = (
    PackageSpec("scholens_ai", "scholens-ai", "scholens_ai"),
    PackageSpec(
        "scholens_job_contracts",
        "scholens-job-contracts",
        "scholens_job_contracts",
    ),
    PackageSpec(
        "scholens_observability",
        "scholens-observability",
        "scholens_observability",
    ),
    PackageSpec(
        "scholens_runtime_contracts",
        "scholens-runtime-contracts",
        "scholens_runtime_contracts",
    ),
)
CONSUMERS = ("server", "jobs")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]*)?$")


def _load_toml(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except FileNotFoundError:
        errors.append(f"missing {path.relative_to(ROOT)}")
        return {}
    except tomllib.TOMLDecodeError as exc:
        errors.append(f"invalid TOML in {path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"expected a TOML table in {path.relative_to(ROOT)}")
        return {}
    return value


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _dependency_name(requirement: object) -> str | None:
    if not isinstance(requirement, str):
        return None
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    return _canonical_name(match.group(1)) if match is not None else None


def _project_table(
    data: dict[str, Any],
    *,
    path: Path,
    errors: list[str],
) -> dict[str, Any]:
    project = data.get("project")
    if not isinstance(project, dict):
        errors.append(f"{path.relative_to(ROOT)} must define [project]")
        return {}
    return project


def _validate_package(spec: PackageSpec, errors: list[str]) -> tuple[str, str]:
    manifest_path = spec.root / "pyproject.toml"
    data = _load_toml(manifest_path, errors)
    project = _project_table(data, path=manifest_path, errors=errors)
    version = project.get("version")
    python_requirement = str(project.get("requires-python", "")).replace(" ", "")

    if _canonical_name(str(project.get("name", ""))) != spec.distribution:
        errors.append(
            f"{manifest_path.relative_to(ROOT)} project.name must be "
            f"{spec.distribution!r}"
        )
    if not isinstance(version, str) or VERSION.fullmatch(version) is None:
        errors.append(
            f"{manifest_path.relative_to(ROOT)} must use an explicit semantic version"
        )
        version = ""
    if python_requirement != EXPECTED_PYTHON:
        errors.append(
            f"{manifest_path.relative_to(ROOT)} requires-python must be "
            f"{EXPECTED_PYTHON!r}"
        )
    if project.get("readme") != "README.md":
        errors.append(f"{manifest_path.relative_to(ROOT)} must declare README.md")

    source_root = spec.root / "src" / spec.import_name
    required_paths = (
        spec.root / "README.md",
        spec.root / "tests",
        source_root / "__init__.py",
        source_root / "py.typed",
    )
    for required in required_paths:
        if not required.exists():
            errors.append(f"missing {required.relative_to(ROOT)}")
    tests = spec.root / "tests"
    if tests.is_dir() and not any(tests.rglob("test_*.py")):
        errors.append(f"{tests.relative_to(ROOT)} must contain direct tests")

    wheel = (
        data.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
    )
    expected_source = f"src/{spec.import_name}"
    if not isinstance(wheel, dict) or expected_source not in wheel.get("packages", []):
        errors.append(
            f"{manifest_path.relative_to(ROOT)} wheel must package {expected_source}"
        )

    if source_root.is_dir():
        _validate_dependency_direction(source_root, errors)
    return version, python_requirement


def _validate_dependency_direction(source_root: Path, errors: list[str]) -> None:
    for path in source_root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
            continue
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported = [node.module]
            for module in imported:
                owner = module.partition(".")[0]
                if owner in FORBIDDEN_APPLICATION_IMPORTS:
                    errors.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} imports application "
                        f"module {owner!r}"
                    )


def _validate_packages_workspace(errors: list[str]) -> None:
    manifest_path = PACKAGES_ROOT / "pyproject.toml"
    data = _load_toml(manifest_path, errors)
    project = _project_table(data, path=manifest_path, errors=errors)
    if str(project.get("requires-python", "")).replace(" ", "") != EXPECTED_PYTHON:
        errors.append(
            f"{manifest_path.relative_to(ROOT)} requires-python must be "
            f"{EXPECTED_PYTHON!r}"
        )
    workspace = data.get("tool", {}).get("uv", {}).get("workspace", {})
    members = workspace.get("members", []) if isinstance(workspace, dict) else []
    expected_members = [spec.directory for spec in PACKAGE_SPECS]
    if sorted(members) != sorted(expected_members):
        errors.append(
            f"{manifest_path.relative_to(ROOT)} workspace members must be "
            f"{expected_members!r}"
        )
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    dependencies = {
        name
        for item in project.get("dependencies", [])
        if (name := _dependency_name(item)) is not None
    }
    for spec in PACKAGE_SPECS:
        if spec.distribution not in dependencies:
            errors.append(
                f"{manifest_path.relative_to(ROOT)} must depend on {spec.distribution}"
            )
        source = sources.get(spec.distribution) if isinstance(sources, dict) else None
        if source != {"workspace": True}:
            errors.append(
                f"{manifest_path.relative_to(ROOT)} must source "
                f"{spec.distribution} from the workspace"
            )


def _validate_consumer(
    consumer: str,
    package_versions: dict[str, str],
    errors: list[str],
) -> None:
    consumer_root = ROOT / consumer
    manifest_path = consumer_root / "pyproject.toml"
    manifest = _load_toml(manifest_path, errors)
    project = _project_table(manifest, path=manifest_path, errors=errors)
    dependencies = {
        name
        for item in project.get("dependencies", [])
        if (name := _dependency_name(item)) is not None
    }
    sources = manifest.get("tool", {}).get("uv", {}).get("sources", {})
    for spec in PACKAGE_SPECS:
        if spec.distribution not in dependencies:
            errors.append(
                f"{manifest_path.relative_to(ROOT)} must depend on {spec.distribution}"
            )
        expected_source = {"path": f"../packages/{spec.directory}"}
        source = sources.get(spec.distribution) if isinstance(sources, dict) else None
        if source != expected_source:
            errors.append(
                f"{manifest_path.relative_to(ROOT)} source for {spec.distribution} "
                f"must be {expected_source!r}"
            )

    lock_path = consumer_root / "uv.lock"
    lock = _load_toml(lock_path, errors)
    if str(lock.get("requires-python", "")).replace(" ", "") != EXPECTED_PYTHON:
        errors.append(
            f"{lock_path.relative_to(ROOT)} requires-python must be {EXPECTED_PYTHON!r}"
        )
    entries = lock.get("package", [])
    if not isinstance(entries, list):
        errors.append(f"{lock_path.relative_to(ROOT)} has no package entries")
        return
    for spec in PACKAGE_SPECS:
        matches = [
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("name") == spec.distribution
        ]
        if len(matches) != 1:
            errors.append(
                f"{lock_path.relative_to(ROOT)} must contain exactly one locked "
                f"{spec.distribution} entry"
            )
            continue
        entry = matches[0]
        expected_source = {"directory": f"../packages/{spec.directory}"}
        if entry.get("source") != expected_source:
            errors.append(
                f"{lock_path.relative_to(ROOT)} has stale source for "
                f"{spec.distribution}"
            )
        if entry.get("version") != package_versions[spec.distribution]:
            errors.append(
                f"{lock_path.relative_to(ROOT)} has stale version for "
                f"{spec.distribution}"
            )


def _validate_packages_lock(
    package_versions: dict[str, str],
    errors: list[str],
) -> None:
    lock_path = PACKAGES_ROOT / "uv.lock"
    lock = _load_toml(lock_path, errors)
    entries = lock.get("package", [])
    if not isinstance(entries, list):
        errors.append(f"{lock_path.relative_to(ROOT)} has no package entries")
        return
    for spec in PACKAGE_SPECS:
        matches = [
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("name") == spec.distribution
        ]
        if len(matches) != 1:
            errors.append(
                f"{lock_path.relative_to(ROOT)} must contain exactly one locked "
                f"{spec.distribution} entry"
            )
            continue
        if matches[0].get("version") != package_versions[spec.distribution]:
            errors.append(
                f"{lock_path.relative_to(ROOT)} has stale version for "
                f"{spec.distribution}"
            )
        expected_source = {"editable": spec.directory}
        if matches[0].get("source") != expected_source:
            errors.append(
                f"{lock_path.relative_to(ROOT)} has stale source for "
                f"{spec.distribution}"
            )


def main() -> int:
    errors: list[str] = []
    _validate_packages_workspace(errors)
    package_versions: dict[str, str] = {}
    for spec in PACKAGE_SPECS:
        version, _python_requirement = _validate_package(spec, errors)
        package_versions[spec.distribution] = version
    _validate_packages_lock(package_versions, errors)
    for consumer in CONSUMERS:
        _validate_consumer(consumer, package_versions, errors)

    if errors:
        print("Shared package workspace contract failed:", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Shared package workspace contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
