from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ecr_scan_contract", ROOT / "scripts/ecr_scan_contract.py"
)
assert SPEC is not None and SPEC.loader is not None
ecr_scan_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ecr_scan_contract)


def _response(digest: str, status: str, *, high: int = 0) -> dict[str, object]:
    return {
        "imageId": {"imageDigest": digest},
        "imageScanStatus": {"status": status},
        "imageScanFindings": {
            "imageScanCompletedAt": "2026-08-16T12:00:00Z",
            "findingSeverityCounts": {"CRITICAL": 0, "HIGH": high},
        },
    }


def test_scan_retries_only_for_the_requested_digest() -> None:
    digest = f"sha256:{'a' * 64}"
    calls: list[tuple[str, str]] = []
    responses = iter((_response(digest, "IN_PROGRESS"), _response(digest, "COMPLETE")))

    result = ecr_scan_contract.wait_for_scan(
        component="api",
        repository="sanchezcloud-scholens-api",
        digest=digest,
        describe=lambda repository, selected: (
            calls.append((repository, selected)) or next(responses)
        ),
        sleep=lambda _: None,
        attempts=2,
    )

    assert result["digest"] == digest
    assert result["scan_digest"] == digest
    assert result["platform"] == "linux/amd64"
    assert calls == [("sanchezcloud-scholens-api", digest)] * 2


def test_old_scan_result_cannot_satisfy_new_digest() -> None:
    digest = f"sha256:{'a' * 64}"
    with pytest.raises(ValueError, match="different digest"):
        ecr_scan_contract.wait_for_scan(
            component="api",
            repository="sanchezcloud-scholens-api",
            digest=digest,
            describe=lambda *_: _response(f"sha256:{'b' * 64}", "COMPLETE"),
            sleep=lambda _: None,
            attempts=1,
        )


@pytest.mark.parametrize("status", ["FAILED", "UNSUPPORTED_IMAGE", "LIMIT_EXCEEDED"])
def test_terminal_or_unsupported_scans_fail_closed(status: str) -> None:
    digest = f"sha256:{'a' * 64}"
    with pytest.raises(ValueError, match="failed closed"):
        ecr_scan_contract.wait_for_scan(
            component="api",
            repository="sanchezcloud-scholens-api",
            digest=digest,
            describe=lambda *_: _response(digest, status),
            sleep=lambda _: None,
            attempts=1,
        )


def test_high_findings_require_a_code_reviewed_policy_change() -> None:
    digest = f"sha256:{'a' * 64}"
    with pytest.raises(ValueError, match="unwaived"):
        ecr_scan_contract.wait_for_scan(
            component="api",
            repository="sanchezcloud-scholens-api",
            digest=digest,
            describe=lambda *_: _response(digest, "COMPLETE", high=1),
            sleep=lambda _: None,
            attempts=1,
        )


def test_scan_not_found_is_retried_until_the_digest_is_indexed() -> None:
    digest = f"sha256:{'a' * 64}"
    missing = subprocess.CalledProcessError(
        254,
        ["aws"],
        stderr="ScanNotFoundException",
    )
    responses = iter((missing, _response(digest, "COMPLETE")))

    def describe(*_):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    result = ecr_scan_contract.wait_for_scan(
        component="api",
        repository="sanchezcloud-scholens-api",
        digest=digest,
        describe=describe,
        sleep=lambda _: None,
        attempts=2,
    )

    assert result["status"] == "COMPLETE"


def test_oci_index_scan_is_bound_to_exact_linux_amd64_child() -> None:
    deployment_digest = f"sha256:{'a' * 64}"
    runtime_digest = f"sha256:{'b' * 64}"
    attestation_digest = f"sha256:{'c' * 64}"
    image = {
        "imageId": {"imageDigest": deployment_digest},
        "imageManifestMediaType": "application/vnd.oci.image.index.v1+json",
        "imageManifest": json.dumps(
            {
                "manifests": [
                    {
                        "digest": runtime_digest,
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "digest": attestation_digest,
                        "platform": {"os": "unknown", "architecture": "unknown"},
                        "annotations": {
                            "vnd.docker.reference.type": "attestation-manifest"
                        },
                    },
                ]
            }
        ),
    }

    assert (
        ecr_scan_contract.linux_amd64_scan_digest(
            "sanchezcloud-scholens-api",
            deployment_digest,
            fetch=lambda *_: image,
        )
        == runtime_digest
    )
