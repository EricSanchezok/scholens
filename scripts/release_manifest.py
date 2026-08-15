#!/usr/bin/env python3
"""Create and verify immutable Scholens ECS release manifests."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
IMAGE_COMPONENTS = ("web", "api", "jobs")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
IMAGE_PATTERN = re.compile(
    r"(?P<account>[0-9]{12})\.dkr\.ecr\.(?P<region>[a-z0-9-]+)\.amazonaws\.com/"
    r"sanchezcloud-scholens-(?P<component>web|api|jobs)@sha256:[0-9a-f]{64}"
)
CHECKSUM_PATTERN = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _literal_assignment(tree: ast.Module, name: str, *, path: Path) -> Any:
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target, ast.Name) and target.id == name for target in targets
            ):
                try:
                    return ast.literal_eval(node.value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{path.name} has a non-literal {name}") from exc
    raise ValueError(f"{path.name} does not define {name}")


def _migration_contract() -> dict[str, str]:
    migrations = sorted((ROOT / "server/migrations/versions").glob("*.py"))
    if not migrations:
        raise ValueError("no Scholens migrations found")
    digest = hashlib.sha256()
    parents_by_revision: dict[str, tuple[str, ...]] = {}
    for migration in migrations:
        digest.update(migration.name.encode())
        digest.update(b"\0")
        contents = migration.read_bytes()
        digest.update(contents)
        digest.update(b"\0")
        tree = ast.parse(contents, filename=str(migration))
        revision = _literal_assignment(tree, "revision", path=migration)
        down_revision = _literal_assignment(tree, "down_revision", path=migration)
        if not isinstance(revision, str) or not revision:
            raise ValueError(f"{migration.name} has an invalid revision")
        if revision in parents_by_revision:
            raise ValueError(f"duplicate migration revision {revision}")
        if down_revision is None:
            parents: tuple[str, ...] = ()
        elif isinstance(down_revision, str):
            parents = (down_revision,)
        elif isinstance(down_revision, (tuple, list)) and all(
            isinstance(value, str) and value for value in down_revision
        ):
            parents = tuple(down_revision)
        else:
            raise ValueError(f"{migration.name} has an invalid down_revision")
        parents_by_revision[revision] = parents
    revisions = set(parents_by_revision)
    referenced = {
        parent for parents in parents_by_revision.values() for parent in parents
    }
    unknown = referenced - revisions
    if unknown:
        raise ValueError(
            f"migration graph references unknown revisions: {sorted(unknown)}"
        )
    heads = revisions - referenced
    if len(heads) != 1:
        raise ValueError(
            f"migration graph must have exactly one head, found {sorted(heads)}"
        )
    head = next(iter(heads))
    reachable: set[str] = set()
    visiting: set[str] = set()

    def visit(revision: str) -> None:
        if revision in visiting:
            raise ValueError("migration graph contains a cycle")
        if revision in reachable:
            return
        visiting.add(revision)
        for parent in parents_by_revision[revision]:
            visit(parent)
        visiting.remove(revision)
        reachable.add(revision)

    visit(head)
    if reachable != revisions:
        raise ValueError(
            "migration graph contains revisions disconnected from its head"
        )
    return {"head": head, "checksum": digest.hexdigest()}


def _validate_source_maps_contract(
    value: object,
    *,
    release_sha: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("source map contract must be an object")
    expected_prefix = f"source-maps/{release_sha}/"
    expected_index_key = f"{expected_prefix}index.json"
    if value.get("prefix") != expected_prefix:
        raise ValueError("source map prefix does not match release SHA")
    if value.get("index_key") != expected_index_key:
        raise ValueError("source map index key does not match release SHA")
    for name in ("index_sha256", "aggregate_sha256"):
        checksum = value.get(name)
        if (
            not isinstance(checksum, str)
            or CHECKSUM_PATTERN.fullmatch(checksum) is None
        ):
            raise ValueError(f"source map {name} is invalid")
    file_count = value.get("file_count")
    if (
        not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or file_count < 1
    ):
        raise ValueError("source map file_count must be a positive integer")
    return {
        "prefix": expected_prefix,
        "index_key": expected_index_key,
        "index_sha256": value["index_sha256"],
        "aggregate_sha256": value["aggregate_sha256"],
        "file_count": file_count,
    }


def _source_maps_contract(path: Path, *, release_sha: str) -> dict[str, Any]:
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("source map index is unreadable") from exc
    if not isinstance(index, dict) or index.get("contract_version") != 1:
        raise ValueError("unsupported source map index contract")
    if index.get("release_sha") != release_sha:
        raise ValueError("source map index SHA does not match release")
    files = index.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("source map index contains no files")
    paths: list[str] = []
    digest = hashlib.sha256()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("source map index entry must be an object")
        relative_path = item.get("path")
        checksum = item.get("sha256")
        size = item.get("size")
        if (
            not isinstance(relative_path, str)
            or relative_path.startswith(("/", "../"))
            or "/../" in relative_path
            or not relative_path.endswith(".map")
        ):
            raise ValueError("source map index contains an unsafe path")
        if (
            not isinstance(checksum, str)
            or CHECKSUM_PATTERN.fullmatch(checksum) is None
        ):
            raise ValueError("source map index contains an invalid checksum")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise ValueError("source map index contains an invalid size")
        paths.append(relative_path)
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update(checksum.encode())
        digest.update(b"\0")
        digest.update(str(size).encode())
        digest.update(b"\n")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("source map index paths must be sorted and unique")
    aggregate = digest.hexdigest()
    if index.get("aggregate_sha256") != aggregate:
        raise ValueError("source map aggregate checksum is invalid")
    return _validate_source_maps_contract(
        {
            "prefix": f"source-maps/{release_sha}/",
            "index_key": f"source-maps/{release_sha}/index.json",
            "index_sha256": _sha256(path),
            "aggregate_sha256": aggregate,
            "file_count": len(files),
        },
        release_sha=release_sha,
    )


def _identity_contract(schema_version: int) -> dict[str, Any]:
    pyproject = tomllib.loads(
        (ROOT / "server/pyproject.toml").read_text(encoding="utf-8")
    )
    dependency = next(
        value
        for value in pyproject["project"]["dependencies"]
        if value.startswith("sanchezcloud-identity")
    )
    reference = dependency.rsplit("@", 1)[-1]
    lock = (ROOT / "server/uv.lock").read_text(encoding="utf-8")
    match = re.search(
        r"sanchezcloud-identity\.git\?(?:rev|tag)=[^#\"\s]+#([0-9a-f]{40})",
        lock,
    )
    if match is None:
        raise ValueError("uv.lock does not pin SanchezCloud Identity to a commit SHA")
    return {
        "reference": reference,
        "commit_sha": match.group(1),
        "schema_version": schema_version,
    }


def _validate_https_url(value: str, *, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise ValueError(f"{name} must be an absolute credential-free HTTPS URL")
    return value.rstrip("/")


def create_manifest(args: argparse.Namespace) -> dict[str, Any]:
    if SHA_PATTERN.fullmatch(args.release_sha) is None:
        raise ValueError("release SHA must be a lowercase 40-character commit SHA")
    if (
        not isinstance(args.identity_schema_version, int)
        or args.identity_schema_version < 1
    ):
        raise ValueError("Identity schema version must be a positive integer")
    try:
        created_at = datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created-at must be ISO-8601") from exc
    if created_at.tzinfo is None:
        raise ValueError("created-at must include a timezone")
    images = {
        component: getattr(args, f"{component}_image") for component in IMAGE_COMPONENTS
    }
    for component, image in images.items():
        match = IMAGE_PATTERN.fullmatch(image)
        if match is None or match.group("component") != component:
            raise ValueError(f"invalid digest-qualified {component} image")
    api_url = _validate_https_url(args.web_api_url, name="web-api-url")
    account_center_url = _validate_https_url(
        args.account_center_url,
        name="account-center-url",
    )
    public_config = {
        "api_url": api_url,
        "account_center_url": account_center_url,
    }
    public_config_bytes = json.dumps(
        public_config,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    source_maps = getattr(args, "source_maps_contract", None)
    if source_maps is None:
        source_maps = _source_maps_contract(
            args.source_maps_index,
            release_sha=args.release_sha,
        )
    else:
        source_maps = _validate_source_maps_contract(
            source_maps,
            release_sha=args.release_sha,
        )
    return {
        "contract_version": 2,
        "release_sha": args.release_sha,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "images": images,
        "identity": _identity_contract(args.identity_schema_version),
        "scholens_migrations": _migration_contract(),
        "public_openapi_sha256": _sha256(ROOT / "server/openapi/public-v1.json"),
        "runtime_template_sha256": _sha256(ROOT / "deploy/ecs/scholens-production.yml"),
        "web_public_config": {
            **public_config,
            "sha256": hashlib.sha256(public_config_bytes).hexdigest(),
        },
        "source_maps": source_maps,
        "artifacts": {
            "attestations": "oci-registry",
            "source_maps": f"source-maps/{args.release_sha}/",
        },
    }


def verify_manifest(
    manifest: dict[str, Any],
    expected_release_sha: str | None = None,
    *,
    expected_account_id: str | None = None,
    expected_region: str | None = None,
) -> None:
    if manifest.get("contract_version") != 2:
        raise ValueError("unsupported release manifest contract")
    release_sha = manifest.get("release_sha")
    if not isinstance(release_sha, str) or SHA_PATTERN.fullmatch(release_sha) is None:
        raise ValueError("invalid release SHA")
    if expected_release_sha is not None and release_sha != expected_release_sha:
        raise ValueError("release manifest SHA does not match the requested release")
    if (expected_account_id is None) != (expected_region is None):
        raise ValueError("expected AWS account and region must be supplied together")
    if expected_account_id is not None and expected_region is not None:
        if re.fullmatch(r"[0-9]{12}", expected_account_id) is None:
            raise ValueError("expected AWS account ID is invalid")
        for component in IMAGE_COMPONENTS:
            image = manifest.get("images", {}).get(component, "")
            match = IMAGE_PATTERN.fullmatch(image)
            if (
                match is None
                or match.group("account") != expected_account_id
                or match.group("region") != expected_region
            ):
                raise ValueError(
                    f"{component} image is not in the expected AWS registry"
                )
    expected = create_manifest(
        argparse.Namespace(
            release_sha=release_sha,
            created_at=manifest.get("created_at"),
            identity_schema_version=manifest.get("identity", {}).get("schema_version"),
            web_api_url=manifest.get("web_public_config", {}).get("api_url"),
            account_center_url=manifest.get("web_public_config", {}).get(
                "account_center_url"
            ),
            source_maps_contract=manifest.get("source_maps"),
            **{
                f"{name}_image": manifest.get("images", {}).get(name, "")
                for name in IMAGE_COMPONENTS
            },
        )
    )
    if manifest != expected:
        raise ValueError(
            "release manifest does not match the checked-out source contract"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--release-sha", required=True)
    create.add_argument("--created-at", required=True)
    create.add_argument("--identity-schema-version", required=True, type=int)
    create.add_argument("--web-api-url", required=True)
    create.add_argument("--account-center-url", required=True)
    for component in IMAGE_COMPONENTS:
        create.add_argument(f"--{component}-image", required=True)
    create.add_argument("--source-maps-index", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--expected-release-sha")
    verify.add_argument("--expected-account-id", required=True)
    verify.add_argument("--expected-region", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "create":
            manifest = create_manifest(args)
            args.output.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            verify_manifest(
                manifest,
                args.expected_release_sha,
                expected_account_id=args.expected_account_id,
                expected_region=args.expected_region,
            )
    except (
        KeyError,
        StopIteration,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"release manifest error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
