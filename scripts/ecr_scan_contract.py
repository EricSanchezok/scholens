#!/usr/bin/env python3
"""Create a fail-closed ECR vulnerability scan contract for exact digests."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

IMAGE = re.compile(
    r"(?P<component>web|api|jobs)=(?P<repository>sanchezcloud-scholens-(?:web|api|jobs))@"
    r"(?P<digest>sha256:[0-9a-f]{64})"
)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
RETRYABLE = {"IN_PROGRESS", "PENDING"}


def _aws_scan(repository: str, digest: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "aws",
            "ecr",
            "describe-image-scan-findings",
            "--repository-name",
            repository,
            "--image-id",
            f"imageDigest={digest}",
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _aws_manifest(repository: str, digest: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "aws",
            "ecr",
            "batch-get-image",
            "--repository-name",
            repository,
            "--image-ids",
            f"imageDigest={digest}",
            "--accepted-media-types",
            "application/vnd.oci.image.index.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.v2+json",
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    response = json.loads(completed.stdout)
    images = response.get("images", [])
    if len(images) != 1 or response.get("failures"):
        raise ValueError("ECR did not return exactly one requested image manifest")
    return images[0]


def linux_amd64_scan_digest(
    repository: str,
    digest: str,
    *,
    fetch: Callable[[str, str], dict[str, Any]] = _aws_manifest,
) -> str:
    """Resolve the deployable OCI index to the exact scanned linux/amd64 image."""
    image = fetch(repository, digest)
    if image.get("imageId", {}).get("imageDigest") != digest:
        raise ValueError("ECR manifest result is for a different deployment digest")
    media_type = image.get("imageManifestMediaType")
    if media_type in {
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    }:
        return digest
    if media_type not in {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }:
        raise ValueError(f"unsupported ECR image media type: {media_type}")
    manifest = json.loads(image.get("imageManifest", ""))
    candidates = [
        item.get("digest")
        for item in manifest.get("manifests", [])
        if item.get("platform", {}).get("os") == "linux"
        and item.get("platform", {}).get("architecture") == "amd64"
        and item.get("annotations", {}).get("vnd.docker.reference.type")
        != "attestation-manifest"
    ]
    if len(candidates) != 1 or DIGEST.fullmatch(str(candidates[0])) is None:
        raise ValueError("image index must contain exactly one linux/amd64 runtime")
    return str(candidates[0])


def wait_for_scan(
    *,
    component: str,
    repository: str,
    digest: str,
    scan_digest: str | None = None,
    describe: Callable[[str, str], dict[str, Any]] = _aws_scan,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 60,
    interval_seconds: float = 10,
) -> dict[str, Any]:
    selected_scan_digest = scan_digest or digest
    for attempt in range(attempts):
        try:
            response = describe(repository, selected_scan_digest)
        except subprocess.CalledProcessError as exc:
            if "ScanNotFoundException" not in (exc.stderr or ""):
                raise
            response = {
                "imageId": {"imageDigest": selected_scan_digest},
                "imageScanStatus": {"status": "PENDING"},
            }
        image_id = response.get("imageId", {})
        if image_id.get("imageDigest") != selected_scan_digest:
            raise ValueError(f"{component} scan result is for a different digest")
        status = response.get("imageScanStatus", {}).get("status")
        if status == "COMPLETE":
            findings = response.get("imageScanFindings", {})
            completed_at = findings.get("imageScanCompletedAt")
            if not isinstance(completed_at, str):
                raise ValueError(f"{component} scan has no completion timestamp")
            parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError(f"{component} scan timestamp lacks timezone")
            counts = findings.get("findingSeverityCounts", {})
            blocked = {
                severity: int(counts.get(severity, 0))
                for severity in ("CRITICAL", "HIGH")
            }
            if any(blocked.values()):
                raise ValueError(f"{component} image has unwaived findings: {blocked}")
            return {
                "digest": digest,
                "scan_digest": selected_scan_digest,
                "platform": "linux/amd64",
                "status": "COMPLETE",
                "completed_at": parsed.isoformat().replace("+00:00", "Z"),
                "findings": blocked,
            }
        if status not in RETRYABLE:
            raise ValueError(f"{component} ECR scan failed closed with status {status}")
        if attempt + 1 < attempts:
            sleep(interval_seconds)
    raise TimeoutError(f"{component} ECR scan did not complete before timeout")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    images: dict[str, tuple[str, str]] = {}
    try:
        for value in args.image:
            match = IMAGE.fullmatch(value)
            if match is None or match.group("component") not in match.group(
                "repository"
            ):
                raise ValueError(f"invalid release image selector: {value}")
            images[match.group("component")] = (
                match.group("repository"),
                match.group("digest"),
            )
        if set(images) != {"web", "api", "jobs"}:
            raise ValueError("scan contract requires exactly web, api, and jobs")
        contract = {
            component: wait_for_scan(
                component=component,
                repository=repository,
                digest=digest,
                scan_digest=linux_amd64_scan_digest(repository, digest),
            )
            for component, (repository, digest) in images.items()
        }
        args.output.write_text(
            json.dumps(contract, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
    ) as exc:
        print(f"ECR scan contract error: {exc}", file=sys.stderr)
        return 2
    except TimeoutError as exc:
        print(f"ECR scan contract error: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
