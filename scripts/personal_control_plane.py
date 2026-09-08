"""Plan or execute a reviewed change set only in the isolated personal account."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any

from personal_deployment import render

ACCOUNT = "669409472143"
REGION = "ap-south-2"
STACKS = {
    "foundation": "sanchezcloud-scholens-foundation",
    "runtime": "sanchezcloud-scholens-production",
}
BUCKET = f"sanchezcloud-scholens-releases-{ACCOUNT}-{REGION}"


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
    if change.get("Description") != f"personal:{stage}:{revision}":
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STACKS)
    parser.add_argument("operation", choices=["plan", "apply"])
    parser.add_argument("--change-set-arn")
    parser.add_argument("--release-sha")
    parser.add_argument(
        "--application-enabled", choices=["true", "false"], default="false"
    )
    args = parser.parse_args()
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

    template = render(args.stage)
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
    overrides = {"ExpectedAccountId": ACCOUNT}
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
            "Description": f"personal:{args.stage}:{revision}",
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
