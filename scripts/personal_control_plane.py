"""Plan or execute a reviewed change set only in the isolated personal account."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tarfile
import time
from typing import Any

from personal_deployment import (
    CACHE_GROUPS,
    CACHE_PARAMETER_FIELDS,
    CACHE_SOURCE_PARAMETERS,
    cache_parameter_pattern,
    render,
)

ACCOUNT = "669409472143"
REGION = "ap-south-2"
STACKS = {
    "foundation": "sanchezcloud-scholens-foundation",
    "runtime": "sanchezcloud-scholens-production",
}
BUCKET = f"sanchezcloud-scholens-releases-{ACCOUNT}-{REGION}"
CACHE_RUNTIME_PARAMETERS = (*CACHE_SOURCE_PARAMETERS, *CACHE_PARAMETER_FIELDS)


def aws(*args: str) -> Any:
    result = subprocess.run(
        ["aws", "--region", REGION, *args, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def guard_destination(account: str, region: str) -> None:
    if account != ACCOUNT or region != REGION:
        raise ValueError(
            "Personal control plane requires the reviewed account and region"
        )


def guard_change(change: dict[str, Any], stage: str, revision: str) -> None:
    if (
        change.get("StackName") != STACKS[stage]
        or change.get("Status") != "CREATE_COMPLETE"
    ):
        raise ValueError("Change set does not belong to the selected stable stack")
    if change.get("Description", "").split(":")[:3] != ["personal", stage, revision]:
        raise ValueError("Change set source revision does not match reviewed code")
    for entry in change.get("Changes", []):
        resource = entry["ResourceChange"]
        if resource["Action"] == "Remove":
            raise ValueError("Resource removal requires a separate migration procedure")
        if (
            resource.get("Replacement") in {"True", "Conditional"}
            and resource["ResourceType"] != "AWS::ECS::TaskDefinition"
        ):
            raise ValueError("Only immutable task definitions may be replaced")
        if resource["ResourceType"] in {
            "AWS::ElasticLoadBalancingV2::LoadBalancer",
            "AWS::EC2::NatGateway",
            "AWS::ElastiCache::ReplicationGroup",
        }:
            raise ValueError(
                "Managed fixed-cost resources are outside the personal topology"
            )


def guard_plan_freshness(change: dict, current: dict, now: datetime) -> None:
    if change.get("ExecutionStatus") != "AVAILABLE":
        return
    created = datetime.fromisoformat(change["CreationTime"])
    updated = datetime.fromisoformat(
        current.get("LastUpdatedTime", current["CreationTime"])
    )
    if not 0 <= (now - created).total_seconds() <= 86400:
        raise ValueError("Plan expired; review a new change set")
    if updated > created:
        raise ValueError("Runtime changed after planning")


def processing_overrides(
    previous: dict, rollout: str, *, shared_inference: bool
) -> dict[str, str]:
    if not shared_inference and previous.get("SharedInferenceEnabled") == "true":
        raise ValueError(
            "Pre-inference rollback requires the documented complete stage drain; "
            "choose a compatible release for ordinary rollback"
        )
    percentage = (
        previous.get("DocumentPipelinePercent", "0")
        if rollout == "preserve"
        else rollout
    )
    if percentage not in {"0", "10", "50", "100"}:
        raise ValueError("Unsupported document rollout cohort")
    if not shared_inference and percentage != "0":
        raise ValueError("Document producers require a consumer-capable release")
    return {
        "SharedInferenceEnabled": "true" if shared_inference else "false",
        "JobResultInboxEnabled": "true" if shared_inference else "false",
        "JobDispatchFairnessEnabled": "true" if shared_inference else "false",
        "DocumentPipelineEnabled": "true" if percentage != "0" else "false",
        "DocumentPipelinePercent": percentage,
    }


def cache_credential_overrides(
    previous: dict[str, str],
    api_source: str = "preserve",
    jobs_source: str = "preserve",
    parameter_arns: dict[str, str] | None = None,
) -> dict[str, str]:
    """Validate non-secret exact references; never fetch credential values."""
    supplied = parameter_arns or {}
    if set(supplied) - set(CACHE_PARAMETER_FIELDS):
        raise ValueError(
            "Only the four reviewed cache parameter ARN fields are accepted"
        )
    if any(not isinstance(value, str) or not value for value in supplied.values()):
        raise ValueError(
            "Cache ARN overrides must be nonempty strings; rollback preserves references"
        )
    result = {name: previous.get(name, "") for name in CACHE_PARAMETER_FIELDS}
    result.update(supplied)
    for group, requested in (("api", api_source), ("jobs", jobs_source)):
        if requested not in {"preserve", "secretsmanager", "ssm"}:
            raise ValueError("Unsupported cache credential source")
        prefix = CACHE_GROUPS[group]
        source_name = f"{prefix}CacheCredentialSource"
        source = (
            previous.get(source_name, "secretsmanager")
            if requested == "preserve"
            else requested
        )
        if source not in {"secretsmanager", "ssm"}:
            raise ValueError("Deployed cache credential source is unsupported")
        result[source_name] = source
        versions = []
        for field in ("username", "password"):
            name = f"{prefix}Cache{field.title()}ParameterArn"
            value = result[name]
            if value:
                match = re.fullmatch(cache_parameter_pattern(group, field), value)
                if not match:
                    raise ValueError(f"Invalid reviewed parameter ARN for {name}")
                versions.append(match.group(1))
        if len(versions) not in {0, 2} or len(set(versions)) > 1:
            raise ValueError(
                "Cache username/password must reference one complete immutable source version"
            )
        if source == "ssm" and len(versions) != 2:
            raise ValueError("SSM cache source requires both approved parameter ARNs")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STACKS)
    parser.add_argument("operation", choices=["plan", "apply"])
    parser.add_argument("--change-set-arn")
    parser.add_argument("--release-sha")
    parser.add_argument(
        "--processing-rollout",
        choices=["preserve", "0", "10", "50", "100"],
        default="preserve",
    )
    parser.add_argument(
        "--background-mode",
        choices=["preserve", "resident", "admitted"],
        default="preserve",
    )
    parser.add_argument(
        "--application-enabled", choices=["true", "false"], default="false"
    )
    for group in CACHE_GROUPS:
        parser.add_argument(
            f"--{group}-cache-credential-source",
            choices=["preserve", "secretsmanager", "ssm"],
            default="preserve",
        )
    parser.add_argument("--cache-parameter-arns", default="{}")
    args = parser.parse_args()
    try:
        cache_arns = json.loads(args.cache_parameter_arns)
    except ValueError as exc:
        raise ValueError(
            "Cache parameter references must be a JSON object of non-secret ARNs"
        ) from exc
    if not isinstance(cache_arns, dict):
        raise ValueError("Cache parameter references must be a JSON object")
    cache_requested = (
        args.api_cache_credential_source != "preserve"
        or args.jobs_cache_credential_source != "preserve"
        or bool(cache_arns)
    )
    if cache_requested and (args.stage != "runtime" or args.operation != "plan"):
        raise ValueError(
            "Cache reference overrides are selected only when planning runtime"
        )
    guard_destination(
        aws("sts", "get-caller-identity")["Account"], os.environ.get("AWS_REGION", "")
    )
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, "origin/main"], check=True
    )
    if args.operation == "apply":
        arn = args.change_set_arn or ""
        if not re.fullmatch(
            rf"arn:aws:cloudformation:{REGION}:{ACCOUNT}:changeSet/github-personal-[\w-]+/[\w-]+",
            arn,
        ):
            raise ValueError(
                "A personal change set ARN from the plan operation is required"
            )
        change = aws("cloudformation", "describe-change-set", "--change-set-name", arn)
        guard_change(change, args.stage, revision)
        current_stack = aws(
            "cloudformation", "describe-stacks", "--stack-name", STACKS[args.stage]
        )["Stacks"][0]
        guard_plan_freshness(change, current_stack, datetime.now(UTC))
        if args.stage == "runtime":
            from release_admission import AdmissionRelease

            planned = {
                p["ParameterKey"]: p.get("ParameterValue") for p in change["Parameters"]
            }
            sha = planned.get("ReleaseSha", "")
            if sha != args.release_sha:
                raise ValueError("Selected release differs from the reviewed plan")
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "manifest.json"
                aws(
                    "s3api",
                    "get-object",
                    "--bucket",
                    BUCKET,
                    "--key",
                    f"releases/{sha}/manifest.json",
                    str(path),
                )
                if (
                    change["Description"].split(":")[-1]
                    != hashlib.sha256(path.read_bytes()).hexdigest()
                ):
                    raise ValueError("Manifest changed after planning")
            if change.get("ExecutionStatus") != "AVAILABLE":
                actual = {
                    p["ParameterKey"]: p.get("ParameterValue")
                    for p in current_stack["Parameters"]
                }
                if current_stack["StackStatus"] == "UPDATE_COMPLETE" and any(
                    actual.get(k) != planned.get(k)
                    for k in (
                        "ReleaseSha",
                        "ApiImage",
                        "WebImage",
                        "JobsImage",
                        *CACHE_RUNTIME_PARAMETERS,
                    )
                ):
                    raise ValueError("Another release superseded this operation")
            AdmissionRelease(arn).run()
            return
        aws("cloudformation", "execute-change-set", "--change-set-name", arn)
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            status = aws(
                "cloudformation", "describe-stacks", "--stack-name", STACKS[args.stage]
            )["Stacks"][0]["StackStatus"]
            if status == "UPDATE_COMPLETE":
                print(json.dumps({"stack": STACKS[args.stage], "status": status}))
                return
            if not status.endswith("IN_PROGRESS"):
                raise RuntimeError(f"Stack did not converge: {status}")
            time.sleep(15)
        raise TimeoutError("Stack convergence requires operator investigation")

    stack = aws(
        "cloudformation", "describe-stacks", "--stack-name", STACKS[args.stage]
    )["Stacks"][0]
    if stack["StackStatus"] not in {
        "CREATE_COMPLETE",
        "UPDATE_COMPLETE",
        "UPDATE_ROLLBACK_COMPLETE",
    }:
        raise ValueError("Existing stack must be stable before planning")
    previous = {x["ParameterKey"] for x in stack["Parameters"]}
    previous_values = {
        x["ParameterKey"]: x["ParameterValue"] for x in stack["Parameters"]
    }
    cache_values = (
        cache_credential_overrides(
            previous_values,
            args.api_cache_credential_source,
            args.jobs_cache_credential_source,
            cache_arns,
        )
        if args.stage == "runtime"
        else {}
    )
    template = render(
        args.stage,
        cache_sources={
            group: cache_values[f"{prefix}CacheCredentialSource"]
            for group, prefix in CACHE_GROUPS.items()
        }
        if args.stage == "runtime"
        else None,
    )
    overrides = {"ExpectedAccountId": ACCOUNT}
    overrides.update(cache_values)
    manifest_hash = ""
    if args.background_mode != "preserve":
        if args.stage != "runtime":
            raise ValueError("Worker mode only belongs to the runtime stack")
        overrides["BackgroundMode"] = args.background_mode
    with tempfile.TemporaryDirectory(prefix="personal-plan-") as directory:
        folder = Path(directory)
        if args.stage == "runtime":
            sha = args.release_sha or ""
            if not re.fullmatch("[0-9a-f]{40}", sha):
                raise ValueError("An immutable release SHA is required")
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", sha, "origin/main"], check=True
            )
            # The personal runtime health contract requires this additive helper.
            subprocess.run(
                [
                    "git",
                    "cat-file",
                    "-e",
                    f"{sha}:packages/scholens_observability/src/scholens_observability/worker_health.py",
                ],
                check=True,
            )
            manifest = folder / "manifest.json"
            source = folder / "source"
            archive = folder / "source.tar"
            subprocess.run(
                [
                    "git",
                    "archive",
                    "--format=tar",
                    "--output",
                    str(archive),
                    sha,
                    "server",
                    "packages/scholens_ai",
                    "deploy/ecs/scholens-production.yml",
                ],
                check=True,
            )
            with tarfile.open(archive) as tar:
                tar.extractall(source, filter="data")
            shared_inference = (
                source / "packages/scholens_ai/src/scholens_ai/inference.py"
            ).is_file()
            overrides.update(
                processing_overrides(
                    previous_values,
                    args.processing_rollout,
                    shared_inference=shared_inference,
                )
            )
            aws(
                "s3api",
                "get-object",
                "--bucket",
                BUCKET,
                "--key",
                f"releases/{sha}/manifest.json",
                str(manifest),
            )
            subprocess.run(
                [
                    "python",
                    "scripts/release_manifest.py",
                    "verify",
                    "--manifest",
                    str(manifest),
                    "--expected-release-sha",
                    sha,
                    "--expected-account-id",
                    ACCOUNT,
                    "--expected-region",
                    REGION,
                    "--expected-platform",
                    "linux/arm64",
                    "--source-root",
                    str(source),
                ],
                check=True,
            )
            if args.application_enabled == "true":
                attestation = folder / "attestation.json"
                current = folder / "current.json"
                aws(
                    "s3api",
                    "get-object",
                    "--bucket",
                    BUCKET,
                    "--key",
                    f"migrations/{sha}/attestation.json",
                    str(attestation),
                )
                aws(
                    "s3api",
                    "get-object",
                    "--bucket",
                    BUCKET,
                    "--key",
                    "migrations/current.json",
                    str(current),
                )
                subprocess.run(
                    [
                        "python",
                        "scripts/release_manifest.py",
                        "verify-database-contract",
                        "--manifest",
                        str(manifest),
                        "--attestation",
                        str(attestation),
                        "--current",
                        str(current),
                    ],
                    check=True,
                )
            data = json.loads(manifest.read_text())
            manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
            overrides.update(
                {
                    "ReleaseSha": sha,
                    "WebImage": data["images"]["web"],
                    "ApiImage": data["images"]["api"],
                    "JobsImage": data["images"]["jobs"],
                    "ApplicationEnabled": args.application_enabled,
                }
            )
        parameters = []
        for key, value in template["Parameters"].items():
            if key in overrides:
                parameters.append(
                    {"ParameterKey": key, "ParameterValue": overrides[key]}
                )
            elif key in previous:
                parameters.append({"ParameterKey": key, "UsePreviousValue": True})
            elif "Default" not in value:
                raise ValueError(
                    f"New parameter {key} needs administrator provisioning"
                )
        name = f"github-personal-{os.environ.get('GITHUB_RUN_ID', 'operator')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
        body = {
            "StackName": STACKS[args.stage],
            "ChangeSetName": name,
            "ChangeSetType": "UPDATE",
            "Description": f"personal:{args.stage}:{revision}"
            + (":" + manifest_hash if manifest_hash else ""),
            "Parameters": parameters,
            "Capabilities": ["CAPABILITY_NAMED_IAM"],
        }
        role = os.environ.get("CLOUDFORMATION_ROLE_ARN", "")
        expected_role = "Foundation" if args.stage == "foundation" else "Runtime"
        if (
            role
            != f"arn:aws:iam::{ACCOUNT}:role/SanchezCloudScholens{expected_role}CloudFormationServiceRole"
        ):
            raise ValueError("Unexpected CloudFormation execution role")
        body["RoleARN"] = role
        if args.stage == "runtime":
            path = folder / "template.json"
            path.write_text(json.dumps(template))
            key = f"cloudformation/personal/{revision}/{name}.json"
            aws(
                "s3api",
                "put-object",
                "--bucket",
                BUCKET,
                "--key",
                key,
                "--body",
                str(path),
                "--if-none-match",
                "*",
            )
            body["TemplateURL"] = f"https://{BUCKET}.s3.{REGION}.amazonaws.com/{key}"
        else:
            body["TemplateBody"] = json.dumps(template)
        path = folder / "request.json"
        path.write_text(json.dumps(body))
        arn = aws(
            "cloudformation", "create-change-set", "--cli-input-json", f"file://{path}"
        )["Id"]
        for _ in range(60):
            change = aws(
                "cloudformation", "describe-change-set", "--change-set-name", arn
            )
            if change["Status"] not in {"CREATE_PENDING", "CREATE_IN_PROGRESS"}:
                break
            time.sleep(5)
        if change["Status"] == "FAILED" and "didn't contain changes" in change.get(
            "StatusReason", ""
        ):
            print("No infrastructure changes")
            return
        guard_change(change, args.stage, revision)
        summary = {
            "change_set_arn": arn,
            "source_sha": revision,
            "stage": args.stage,
            "changes": [x["ResourceChange"] for x in change.get("Changes", [])],
        }
        Path("personal-change-set.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
