#!/usr/bin/env python3
"""Create and verify immutable Scholens ECS release manifests."""

from __future__ import annotations

import argparse
import ast
import hashlib
import ipaddress
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
SCAN_SEVERITIES = ("CRITICAL", "HIGH")
DNS_LABEL_PATTERN = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
TASK_DEFINITION_REGISTRATION_FIELDS = (
    "family",
    "taskRoleArn",
    "executionRoleArn",
    "networkMode",
    "containerDefinitions",
    "volumes",
    "placementConstraints",
    "requiresCompatibilities",
    "cpu",
    "memory",
    "runtimePlatform",
    "ephemeralStorage",
)


def _source_root(path: Path) -> Path:
    root = path.resolve()
    required = (
        root / "server" / "pyproject.toml",
        root / "server" / "uv.lock",
        root / "deploy" / "ecs" / "scholens-production.yml",
    )
    if not root.is_dir() or not all(item.is_file() for item in required):
        raise ValueError("source root does not contain a complete Scholens release")
    return root


def _template_parameter_names(path: Path) -> tuple[str, ...]:
    """Read top-level CloudFormation parameter names without executing old source."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("CloudFormation template is unreadable") from exc
    in_parameters = False
    names: list[str] = []
    for line in lines:
        if not in_parameters:
            if line == "Parameters:":
                in_parameters = True
            continue
        if line and not line[0].isspace():
            break
        match = re.fullmatch(r"  ([A-Za-z][A-Za-z0-9]*):(?:.*)", line)
        if match is not None:
            names.append(match.group(1))
    if not in_parameters or not names or len(names) != len(set(names)):
        raise ValueError("CloudFormation template has an invalid Parameters section")
    return tuple(names)


def migration_candidate_task_definition(
    task_definition: object,
    candidate_image: str,
) -> dict[str, Any]:
    """Clone an ECS migration task onto one exact API image digest."""
    image_match = IMAGE_PATTERN.fullmatch(candidate_image)
    if image_match is None or image_match.group("component") != "api":
        raise ValueError(
            "candidate migration image must be a digest-qualified API image"
        )
    if not isinstance(task_definition, dict):
        raise ValueError("base migration task definition must be an object")
    containers = task_definition.get("containerDefinitions")
    if not isinstance(containers, list) or not all(
        isinstance(container, dict) for container in containers
    ):
        raise ValueError("base migration task definition has invalid containers")
    migration_containers = [
        container for container in containers if container.get("name") == "migration"
    ]
    if len(migration_containers) != 1:
        raise ValueError(
            "base migration task definition must contain exactly one migration container"
        )
    base_image = migration_containers[0].get("image")
    if not isinstance(base_image, str) or not base_image:
        raise ValueError("base migration container image is invalid")

    candidate = {
        field: task_definition[field]
        for field in TASK_DEFINITION_REGISTRATION_FIELDS
        if task_definition.get(field) is not None
    }
    candidate_containers: list[dict[str, Any]] = []
    for container in containers:
        cloned = dict(container)
        if cloned.get("image") == base_image:
            cloned["image"] = candidate_image
        candidate_containers.append(cloned)
    candidate["containerDefinitions"] = candidate_containers
    migrated = next(
        container
        for container in candidate_containers
        if container.get("name") == "migration"
    )
    if migrated.get("image") != candidate_image:
        raise ValueError("candidate migration container image was not replaced")
    return candidate


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


def _migration_graph() -> tuple[list[dict[str, str | None]], str]:
    migrations = sorted((ROOT / "server/migrations/versions").glob("*.py"))
    if not migrations:
        raise ValueError("no Scholens migrations found")
    digest = hashlib.sha256()
    entries_by_revision: dict[str, dict[str, str | None]] = {}
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
        if revision in entries_by_revision:
            raise ValueError(f"duplicate migration revision {revision}")
        if down_revision is not None and (
            not isinstance(down_revision, str) or not down_revision
        ):
            raise ValueError(f"{migration.name} has an invalid down_revision")
        entries_by_revision[revision] = {
            "revision": revision,
            "down_revision": down_revision,
            "filename": migration.name,
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
    revisions = set(entries_by_revision)
    referenced = {
        parent
        for entry in entries_by_revision.values()
        if (parent := entry["down_revision"]) is not None
    }
    unknown = referenced.difference(revisions)
    if unknown:
        raise ValueError(
            f"migration graph references unknown revisions: {sorted(unknown)}"
        )
    roots = [
        revision
        for revision, entry in entries_by_revision.items()
        if entry["down_revision"] is None
    ]
    if len(roots) != 1:
        raise ValueError(
            f"migration graph must have exactly one root, found {sorted(roots)}"
        )
    children: dict[str, list[str]] = {revision: [] for revision in revisions}
    for revision, entry in entries_by_revision.items():
        parent = entry["down_revision"]
        if parent is not None:
            children[parent].append(revision)
    branches = {
        revision: values for revision, values in children.items() if len(values) > 1
    }
    if branches:
        raise ValueError(
            f"migration graph must remain linear, found branches: {sorted(branches)}"
        )
    ordered: list[dict[str, str | None]] = []
    current: str | None = roots[0]
    while current is not None:
        ordered.append(entries_by_revision[current])
        current = children[current][0] if children[current] else None
    if len(ordered) != len(revisions):
        raise ValueError("migration graph contains a cycle or disconnected revision")
    return ordered, digest.hexdigest()


def _migration_contract_legacy() -> dict[str, str]:
    ordered, checksum = _migration_graph()
    return {"head": str(ordered[-1]["revision"]), "checksum": checksum}


def _migration_contract() -> dict[str, Any]:
    ordered, checksum = _migration_graph()
    policy_path = ROOT / "server/migrations/policy.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("migration policy is missing or invalid") from exc
    if policy.get("contract_version") != 1:
        raise ValueError("migration policy has an unsupported contract version")
    policy_revisions = policy.get("revisions")
    if not isinstance(policy_revisions, dict):
        raise ValueError("migration policy revisions must be an object")
    revision_names = [str(entry["revision"]) for entry in ordered]
    if set(policy_revisions) != set(revision_names):
        raise ValueError("migration policy must classify every revision exactly once")
    baseline = policy.get("production_baseline_revision")
    if baseline not in revision_names:
        raise ValueError("migration policy production baseline is not in the chain")
    baseline_index = revision_names.index(str(baseline))
    floor = str(baseline)
    floor_index = baseline_index
    enriched: list[dict[str, str | None]] = []
    for index, entry in enumerate(ordered):
        revision = str(entry["revision"])
        metadata = policy_revisions[revision]
        if not isinstance(metadata, dict):
            raise ValueError(f"migration policy for {revision} must be an object")
        phase = metadata.get("phase")
        allowed_keys = {"phase"}
        if index <= baseline_index:
            if phase != "baseline":
                raise ValueError(
                    "revisions through the production baseline must be baseline"
                )
        elif phase == "expand":
            pass
        elif phase == "contract":
            allowed_keys.add("minimum_compatible_application_revision")
            proposed_floor = metadata.get("minimum_compatible_application_revision")
            if proposed_floor not in revision_names[: index + 1]:
                raise ValueError(
                    f"contract migration {revision} has an invalid compatibility floor"
                )
            proposed_index = revision_names.index(str(proposed_floor))
            if proposed_index < floor_index:
                raise ValueError("migration compatibility floor cannot move backward")
            floor = str(proposed_floor)
            floor_index = proposed_index
        else:
            raise ValueError(f"migration {revision} has an invalid evolution phase")
        if set(metadata) != allowed_keys:
            raise ValueError(f"migration policy for {revision} has unsupported fields")
        enriched.append({**entry, "phase": str(phase)})
    return {
        "head": revision_names[-1],
        "checksum": checksum,
        "production_baseline_revision": str(baseline),
        "minimum_compatible_application_revision": floor,
        "revisions": enriched,
    }


def _validate_source_maps_contract(
    value: object,
    *,
    release_sha: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("source map contract must be an object")
    for name in ("index_sha256", "aggregate_sha256"):
        checksum = value.get(name)
        if (
            not isinstance(checksum, str)
            or CHECKSUM_PATTERN.fullmatch(checksum) is None
        ):
            raise ValueError(f"source map {name} is invalid")
    expected_prefix = f"source-maps/{release_sha}/{value['aggregate_sha256']}/"
    expected_index_key = f"{expected_prefix}index.json"
    if value.get("prefix") != expected_prefix:
        raise ValueError("source map prefix is not content-addressed")
    if value.get("index_key") != expected_index_key:
        raise ValueError("source map index key does not match its content address")
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
            "prefix": f"source-maps/{release_sha}/{aggregate}/",
            "index_key": f"source-maps/{release_sha}/{aggregate}/index.json",
            "index_sha256": _sha256(path),
            "aggregate_sha256": aggregate,
            "file_count": len(files),
        },
        release_sha=release_sha,
    )


def _identity_resolution() -> tuple[str, str]:
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
        r"sanchezcloud-identity\.git\?(?:rev|tag)=([^#\"\s]+)#([0-9a-f]{40})",
        lock,
    )
    if match is None:
        raise ValueError("uv.lock does not pin SanchezCloud Identity to a commit SHA")
    if match.group(1) != reference:
        raise ValueError("uv.lock Identity reference does not match pyproject.toml")
    return reference, match.group(2)


def _identity_contract(schema_version: int) -> dict[str, Any]:
    reference, commit_sha = _identity_resolution()
    return {
        "reference": reference,
        "commit_sha": commit_sha,
        "schema_version": schema_version,
    }


def _validate_image_scans(value: object, *, images: dict[str, str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(IMAGE_COMPONENTS):
        raise ValueError("image scan contract must cover every release image")
    scans: dict[str, Any] = {}
    for component in IMAGE_COMPONENTS:
        item = value.get(component)
        if not isinstance(item, dict):
            raise ValueError(f"{component} image scan contract must be an object")
        digest = images[component].rsplit("@", 1)[-1]
        if item.get("digest") != digest or item.get("status") != "COMPLETE":
            raise ValueError(f"{component} image scan does not match its digest")
        scan_digest = item.get("scan_digest")
        if (
            not isinstance(scan_digest, str)
            or CHECKSUM_PATTERN.fullmatch(scan_digest.removeprefix("sha256:")) is None
        ):
            raise ValueError(f"{component} image scan digest is invalid")
        if item.get("platform") != "linux/amd64":
            raise ValueError(f"{component} image scan platform is invalid")
        try:
            completed_at = datetime.fromisoformat(
                str(item.get("completed_at", "")).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(f"{component} image scan timestamp is invalid") from exc
        if completed_at.tzinfo is None:
            raise ValueError(f"{component} image scan timestamp lacks timezone")
        findings = item.get("findings")
        if not isinstance(findings, dict) or set(findings) != set(SCAN_SEVERITIES):
            raise ValueError(f"{component} image scan severities are incomplete")
        if any(findings[severity] != 0 for severity in SCAN_SEVERITIES):
            raise ValueError(f"{component} image has unwaived HIGH/CRITICAL findings")
        scans[component] = {
            "digest": digest,
            "scan_digest": scan_digest,
            "platform": "linux/amd64",
            "status": "COMPLETE",
            "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
            "findings": {severity: 0 for severity in SCAN_SEVERITIES},
        }
    return scans


def _validate_https_url(value: str, *, name: str) -> str:
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        port = parsed.port
        if hostname is None:
            ascii_hostname = ""
        else:
            try:
                ipaddress.ip_address(hostname)
                ascii_hostname = hostname
            except ValueError:
                ascii_hostname = hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be an absolute credential-free HTTPS URL"
        ) from exc
    dns_hostname = ascii_hostname.removesuffix(".")
    hostname_is_valid = bool(ascii_hostname) and (
        ":" in ascii_hostname
        or (
            len(dns_hostname) <= 253
            and all(
                DNS_LABEL_PATTERN.fullmatch(label) is not None
                for label in dns_hostname.split(".")
            )
        )
    )
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not hostname_is_valid
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or parsed.netloc.endswith(":")
        or port == 0
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{name} must be an absolute credential-free HTTPS URL")
    return value.rstrip("/")


def _create_manifest(
    args: argparse.Namespace,
    *,
    legacy: bool,
) -> dict[str, Any]:
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
    image_scans = getattr(args, "image_scans_contract", None)
    if image_scans is None:
        image_scans = json.loads(
            args.image_scan_attestation.read_text(encoding="utf-8")
        )
    image_scans = _validate_image_scans(image_scans, images=images)
    manifest = {
        "contract_version": 2 if legacy else 3,
        "release_sha": args.release_sha,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "images": images,
        "image_scans": image_scans,
        "identity": _identity_contract(args.identity_schema_version),
        "scholens_migrations": (
            _migration_contract_legacy() if legacy else _migration_contract()
        ),
        "public_openapi_sha256": _sha256(ROOT / "server/openapi/public-v1.json"),
        "runtime_template_sha256": _sha256(ROOT / "deploy/ecs/scholens-production.yml"),
        "web_public_config": {
            **public_config,
            "sha256": hashlib.sha256(public_config_bytes).hexdigest(),
        },
        "source_maps": source_maps,
        "artifacts": {
            "attestations": "oci-registry",
            "migration_attestation": (
                f"migrations/{args.release_sha}/attestation.json"
            ),
            "source_maps": source_maps["prefix"],
        },
    }
    if not legacy:
        manifest["public_mcp_sha256"] = _sha256(ROOT / "server/contracts/mcp-v1.json")
    return manifest


def create_manifest(args: argparse.Namespace) -> dict[str, Any]:
    return _create_manifest(args, legacy=False)


def verify_manifest(
    manifest: dict[str, Any],
    expected_release_sha: str | None = None,
    *,
    expected_account_id: str | None = None,
    expected_region: str | None = None,
) -> None:
    contract_version = manifest.get("contract_version")
    if contract_version not in {2, 3}:
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
    expected = _create_manifest(
        argparse.Namespace(
            release_sha=release_sha,
            created_at=manifest.get("created_at"),
            identity_schema_version=manifest.get("identity", {}).get("schema_version"),
            web_api_url=manifest.get("web_public_config", {}).get("api_url"),
            account_center_url=manifest.get("web_public_config", {}).get(
                "account_center_url"
            ),
            source_maps_contract=manifest.get("source_maps"),
            image_scans_contract=manifest.get("image_scans"),
            **{
                f"{name}_image": manifest.get("images", {}).get(name, "")
                for name in IMAGE_COMPONENTS
            },
        ),
        legacy=contract_version == 2,
    )
    if manifest != expected:
        raise ValueError(
            "release manifest does not match the checked-out source contract"
        )


def _validate_runtime_migration_proof(
    proof: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    expected = {
        "contract_version": 1,
        "release_sha": manifest["release_sha"],
        "scholens": {
            "current_revisions": [manifest["scholens_migrations"]["head"]],
            "expected_revisions": [manifest["scholens_migrations"]["head"]],
            "up_to_date": True,
        },
        "identity": {
            "policy": "exact",
            "required_schema_version": manifest["identity"]["schema_version"],
            "installed_schema_version": manifest["identity"]["schema_version"],
        },
    }
    if proof != expected:
        raise ValueError("runtime migration proof does not match the release contract")
    return expected


def migration_attestation(
    manifest: dict[str, Any],
    runtime_proof: object | None = None,
) -> dict[str, Any]:
    """Build a retry-safe proof that the manifest's database contract ran."""
    verify_manifest(manifest)
    canonical_manifest = json.dumps(
        manifest,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if runtime_proof is None:
        runtime_proof = {
            "contract_version": 1,
            "release_sha": manifest["release_sha"],
            "scholens": {
                "current_revisions": [manifest["scholens_migrations"]["head"]],
                "expected_revisions": [manifest["scholens_migrations"]["head"]],
                "up_to_date": True,
            },
            "identity": {
                "policy": "exact",
                "required_schema_version": manifest["identity"]["schema_version"],
                "installed_schema_version": manifest["identity"]["schema_version"],
            },
        }
    proof = _validate_runtime_migration_proof(runtime_proof, manifest)
    return {
        "contract_version": 1 if manifest["contract_version"] == 2 else 2,
        "release_sha": manifest["release_sha"],
        "release_manifest_sha256": hashlib.sha256(canonical_manifest).hexdigest(),
        "scholens_migrations": manifest["scholens_migrations"],
        "identity": manifest["identity"],
        "database_runtime_proof": proof,
    }


def verify_migration_attestation(
    attestation: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    if attestation != migration_attestation(manifest):
        raise ValueError("migration attestation does not match the release manifest")


def _migration_revision_names(
    contract: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    revisions = contract.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        raise ValueError(f"{label} migration revision history is invalid")
    names: list[str] = []
    previous: str | None = None
    for entry in revisions:
        if not isinstance(entry, dict):
            raise ValueError(f"{label} migration revision history is invalid")
        revision = entry.get("revision")
        if (
            not isinstance(revision, str)
            or not revision
            or entry.get("down_revision") != previous
            or CHECKSUM_PATTERN.fullmatch(str(entry.get("sha256", ""))) is None
            or entry.get("phase") not in {"baseline", "expand", "contract"}
        ):
            raise ValueError(f"{label} migration revision history is invalid")
        names.append(revision)
        previous = revision
    if len(names) != len(set(names)) or contract.get("head") != names[-1]:
        raise ValueError(f"{label} migration revision history is invalid")
    if CHECKSUM_PATTERN.fullmatch(str(contract.get("checksum", ""))) is None:
        raise ValueError(f"{label} migration checksum is invalid")
    if contract.get("production_baseline_revision") not in names:
        raise ValueError(f"{label} migration baseline is invalid")
    if contract.get("minimum_compatible_application_revision") not in names:
        raise ValueError(f"{label} migration compatibility floor is invalid")
    return names


def verify_current_database_contract(
    current: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    """Require the live database contract to remain compatible with a release."""
    current_version = current.get("contract_version")
    if current_version not in {1, 2}:
        raise ValueError("current database proof has an unsupported contract")
    if SHA_PATTERN.fullmatch(str(current.get("release_sha", ""))) is None:
        raise ValueError("current database proof has an invalid release SHA")
    if (
        CHECKSUM_PATTERN.fullmatch(str(current.get("release_manifest_sha256", "")))
        is None
    ):
        raise ValueError("current database proof has an invalid manifest checksum")
    if current.get("identity") != manifest.get("identity"):
        raise ValueError("current Identity contract does not match release")
    current_migrations = current.get("scholens_migrations")
    target_migrations = manifest.get("scholens_migrations")
    if not isinstance(current_migrations, dict) or not isinstance(
        target_migrations, dict
    ):
        raise ValueError("database migration contract is invalid")
    if manifest.get("contract_version") == 2:
        if current_version == 1:
            compatible = current_migrations == target_migrations
        else:
            current_revisions = current_migrations.get("revisions")
            current_names = _migration_revision_names(
                current_migrations,
                label="current",
            )
            target_revisions, target_checksum = _migration_graph()
            target_head = target_migrations.get("head")
            try:
                target_index = current_names.index(target_head)
                floor_index = current_names.index(
                    current_migrations.get("minimum_compatible_application_revision")
                )
            except ValueError:
                compatible = False
            else:
                compatible = (
                    target_checksum == target_migrations.get("checksum")
                    and target_head == target_revisions[-1]["revision"]
                    and target_index >= floor_index
                    and len(target_revisions) == target_index + 1
                    and all(
                        all(
                            current_entry.get(key) == target_entry[key]
                            for key in target_entry
                        )
                        for current_entry, target_entry in zip(
                            current_revisions,
                            target_revisions,
                            strict=False,
                        )
                    )
                )
        if not compatible:
            raise ValueError(
                "current database migration contract does not match release"
            )
        return
    if current_version != 2:
        raise ValueError("current database proof predates compatibility ranges")
    current_revisions = current_migrations.get("revisions")
    target_revisions = target_migrations.get("revisions")
    current_names = _migration_revision_names(current_migrations, label="current")
    _migration_revision_names(target_migrations, label="release")
    if current_migrations.get("production_baseline_revision") != target_migrations.get(
        "production_baseline_revision"
    ):
        raise ValueError("current database migration baseline does not match release")
    target_head = target_migrations.get("head")
    try:
        target_index = current_names.index(target_head)
        floor_index = current_names.index(
            current_migrations.get("minimum_compatible_application_revision")
        )
    except ValueError as exc:
        raise ValueError(
            "release revision is outside the live compatibility range"
        ) from exc
    if (
        target_index < floor_index
        or target_revisions != current_revisions[: target_index + 1]
    ):
        raise ValueError("release revision is outside the live compatibility range")


def verify_migration_transition(
    current: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    """Require a candidate to append to the attested production migration chain."""
    verify_manifest(manifest)
    if manifest.get("contract_version") != 3:
        raise ValueError("new migrations require a version 3 release manifest")
    candidate = manifest["scholens_migrations"]
    current_version = current.get("contract_version")
    previous = current.get("scholens_migrations")
    if not isinstance(previous, dict):
        raise ValueError("current database migration contract is invalid")
    if current_version == 1:
        baseline = candidate["production_baseline_revision"]
        if (
            previous.get("head") != baseline
            or candidate.get("head") != baseline
            or previous.get("checksum") != candidate.get("checksum")
        ):
            raise ValueError(
                "legacy database proof must first transition at the production baseline"
            )
        return
    if current_version != 2:
        raise ValueError("current database proof has an unsupported contract")
    previous_revisions = previous.get("revisions")
    candidate_revisions = candidate.get("revisions")
    previous_names = _migration_revision_names(previous, label="current")
    candidate_names = _migration_revision_names(candidate, label="candidate")
    if previous.get("production_baseline_revision") != candidate.get(
        "production_baseline_revision"
    ):
        raise ValueError("production migration baseline changed")
    if candidate_revisions[: len(previous_revisions)] != previous_revisions:
        raise ValueError("candidate rewrites or removes an attested migration")
    if candidate_names[: len(previous_names)] != previous_names:
        raise ValueError("candidate rewrites or removes an attested migration")
    try:
        previous_floor = candidate_names.index(
            previous.get("minimum_compatible_application_revision")
        )
        candidate_floor = candidate_names.index(
            candidate.get("minimum_compatible_application_revision")
        )
    except ValueError as exc:
        raise ValueError("migration compatibility floor is not in the chain") from exc
    if candidate_floor < previous_floor:
        raise ValueError("migration compatibility floor cannot move backward")


def verify_database_contract(
    attestation: dict[str, Any],
    current: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    verify_migration_attestation(attestation, manifest)
    verify_current_database_contract(current, manifest)


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
    create.add_argument("--image-scan-attestation", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--expected-release-sha")
    verify.add_argument("--expected-account-id", required=True)
    verify.add_argument("--expected-region", required=True)
    verify.add_argument("--source-root", type=Path)
    create_attestation = subparsers.add_parser("create-migration-attestation")
    create_attestation.add_argument("--manifest", type=Path, required=True)
    create_attestation.add_argument("--runtime-proof", type=Path, required=True)
    create_attestation.add_argument("--output", type=Path, required=True)
    create_attestation.add_argument("--source-root", type=Path)
    verify_attestation = subparsers.add_parser("verify-migration-attestation")
    verify_attestation.add_argument("--manifest", type=Path, required=True)
    verify_attestation.add_argument("--attestation", type=Path, required=True)
    verify_attestation.add_argument("--source-root", type=Path)
    verify_database = subparsers.add_parser("verify-database-contract")
    verify_database.add_argument("--manifest", type=Path, required=True)
    verify_database.add_argument("--attestation", type=Path, required=True)
    verify_database.add_argument("--current", type=Path, required=True)
    verify_database.add_argument("--source-root", type=Path)
    verify_transition = subparsers.add_parser("verify-migration-transition")
    verify_transition.add_argument("--manifest", type=Path, required=True)
    verify_transition.add_argument("--current", type=Path, required=True)
    verify_transition.add_argument("--source-root", type=Path)
    verify_scans = subparsers.add_parser("verify-image-scans")
    verify_scans.add_argument("--manifest", type=Path, required=True)
    verify_scans.add_argument("--image-scan-attestation", type=Path, required=True)
    subparsers.add_parser("identity-revision")
    migration_head = subparsers.add_parser("migration-head")
    migration_head.add_argument("--source-root", type=Path)
    template_parameters = subparsers.add_parser("template-parameters")
    template_parameters.add_argument("--template", type=Path, required=True)
    candidate_task = subparsers.add_parser("migration-candidate-task-definition")
    candidate_task.add_argument("--base-task-definition", type=Path, required=True)
    candidate_task.add_argument("--api-image", required=True)
    candidate_task.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    global ROOT
    args = _parser().parse_args()
    try:
        source_root = getattr(args, "source_root", None)
        if source_root is not None:
            ROOT = _source_root(source_root)
        if args.command == "create":
            manifest = create_manifest(args)
            args.output.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif args.command == "verify":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            verify_manifest(
                manifest,
                args.expected_release_sha,
                expected_account_id=args.expected_account_id,
                expected_region=args.expected_region,
            )
        elif args.command == "identity-revision":
            print(_identity_resolution()[1])
        elif args.command == "migration-head":
            print(_migration_contract_legacy()["head"])
        elif args.command == "template-parameters":
            for name in _template_parameter_names(args.template):
                print(name)
        elif args.command == "migration-candidate-task-definition":
            task_definition = json.loads(
                args.base_task_definition.read_text(encoding="utf-8")
            )
            candidate = migration_candidate_task_definition(
                task_definition,
                args.api_image,
            )
            args.output.write_text(
                json.dumps(candidate, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif args.command == "create-migration-attestation":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            runtime_proof = json.loads(args.runtime_proof.read_text(encoding="utf-8"))
            attestation = migration_attestation(manifest, runtime_proof)
            args.output.write_text(
                json.dumps(attestation, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif args.command == "verify-migration-attestation":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            attestation = json.loads(args.attestation.read_text(encoding="utf-8"))
            verify_migration_attestation(attestation, manifest)
        elif args.command == "verify-database-contract":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            attestation = json.loads(args.attestation.read_text(encoding="utf-8"))
            current = json.loads(args.current.read_text(encoding="utf-8"))
            verify_database_contract(attestation, current, manifest)
        elif args.command == "verify-migration-transition":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            current = json.loads(args.current.read_text(encoding="utf-8"))
            verify_migration_transition(current, manifest)
        else:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            scans = json.loads(args.image_scan_attestation.read_text(encoding="utf-8"))
            live = _validate_image_scans(scans, images=manifest["images"])
            recorded = _validate_image_scans(
                manifest.get("image_scans"), images=manifest["images"]
            )
            for component in IMAGE_COMPONENTS:
                for field in (
                    "digest",
                    "scan_digest",
                    "platform",
                    "status",
                    "findings",
                ):
                    if live[component][field] != recorded[component][field]:
                        raise ValueError(
                            "live ECR scan results do not match release manifest"
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
