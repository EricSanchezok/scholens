"""Drain and atomically refresh this product's admitted worker registrations."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ACCOUNT = "669409472143"
REGION = "ap-south-2"
CLUSTER = "sanchezcloud-personal"
RUNTIME = "sanchezcloud-scholens-production"
BACKGROUND = "scholens-personal-background"
BUCKET = f"sanchezcloud-scholens-releases-{ACCOUNT}-{REGION}"
ROLE = (
    f"arn:aws:iam::{ACCOUNT}:role/SanchezCloudScholensRuntimeCloudFormationServiceRole"
)
WORKERS = {
    "Document": "document",
    "DocumentIndex": "document-index",
    "DocumentEnrichment": "document-enrichment",
    "Research": "research",
    "Maintenance": "maintenance",
}
NAMES = {"scholens-" + queue for queue in WORKERS.values()}
PREFIX = "/sanchezcloud/personal/background/"


def registration_names(parameters: dict) -> set[str]:
    present = {key for key in WORKERS if key + "TaskArn" in parameters}
    if present not in ({"Document", "Research", "Maintenance"}, set(WORKERS)):
        raise ValueError("Incomplete product registration topology")
    return {"scholens-" + WORKERS[key] for key in present}


def acknowledged(status: dict, expected: dict, now: float) -> bool:
    return (
        status.get("account") == ACCOUNT
        and status.get("region") == REGION
        and status.get("cluster") == CLUSTER
        and 0 <= now - status.get("observed_at", 0) <= 90
        and status.get("registration_refreshed_at", 0) > 0
        and all(
            status.get("registrations", {}).get(k) == v for k, v in expected.items()
        )
    )


def unsettled(tasks: list[dict], names: set[str]) -> bool:
    return any(
        t.get("group") in {"background:" + n for n in names}
        and t.get("lastStatus") != "STOPPED"
        for t in tasks
    )


def guard_registration_change(change: dict, *, expanding: bool = False) -> None:
    allowed = {key + "Registration" for key in WORKERS} | {"AdmissionGrant"}
    additions = {"DocumentIndexRegistration", "DocumentEnrichmentRegistration"}
    for item in change.get("Changes", []):
        r = item["ResourceChange"]
        if (
            not (
                r["Action"] == "Modify"
                or (
                    expanding
                    and r["Action"] == "Add"
                    and r["LogicalResourceId"] in additions
                )
            )
            or r["LogicalResourceId"] not in allowed
            or r.get("Replacement") in {"True", "Conditional"}
        ):
            raise ValueError(
                "Only owned registrations and their grant may change; expansion is explicit"
            )


class AdmissionRelease:
    def __init__(self, change_arn: str):
        session = boto3.Session(region_name=REGION)
        cfg = Config(
            connect_timeout=8, read_timeout=30, retries={"total_max_attempts": 3}
        )
        if (
            session.client("sts", config=cfg).get_caller_identity()["Account"]
            != ACCOUNT
        ):
            raise ValueError("Unexpected deployment account")
        self.cf = session.client("cloudformation", config=cfg)
        self.ecs = session.client("ecs", config=cfg)
        self.ssm = session.client("ssm", config=cfg)
        self.s3 = session.client("s3", config=cfg)
        self.arn = change_arn
        self.operation = change_arn.rsplit("/", 1)[-1]
        self.prefix = f"cloudformation/personal/releases/{self.operation}/"

    def read(self, name: str) -> dict | None:
        try:
            return json.loads(
                self.s3.get_object(Bucket=BUCKET, Key=self.prefix + name + ".json")[
                    "Body"
                ].read()
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "NoSuchKey":
                raise
            return None

    def record(self, name: str, value: dict) -> None:
        previous = self.read(name)
        if previous is not None:
            if previous != value:
                raise ValueError(
                    "Release checkpoint conflicts with the original operation"
                )
            return
        self.s3.put_object(
            Bucket=BUCKET,
            Key=self.prefix + name + ".json",
            Body=json.dumps(value, sort_keys=True).encode(),
            ContentType="application/json",
            IfNoneMatch="*",
        )

    def stack(self, name: str) -> dict:
        return self.cf.describe_stacks(StackName=name)["Stacks"][0]

    def wait_stack(self, name: str) -> None:
        for _ in range(180):
            status = self.stack(name)["StackStatus"]
            if status == "UPDATE_COMPLETE":
                return
            if not status.endswith("IN_PROGRESS"):
                raise RuntimeError(
                    f"Stack did not converge: {name} {status}; admission stays paused"
                )
            time.sleep(10)
        raise TimeoutError("Stack update needs investigation; admission stays paused")

    def change_background(self, stage: str, overrides: dict) -> None:
        name = "release-" + self.operation + "-" + stage
        current = self.stack(BACKGROUND)
        actual = {p["ParameterKey"]: p["ParameterValue"] for p in current["Parameters"]}
        if current["StackStatus"].endswith("IN_PROGRESS"):
            self.wait_stack(BACKGROUND)
            current = self.stack(BACKGROUND)
            actual = {
                p["ParameterKey"]: p["ParameterValue"] for p in current["Parameters"]
            }
        if all(actual.get(k) == v for k, v in overrides.items()):
            return
        expanding = stage == "revisions" and "DocumentIndexTaskArn" not in actual
        new_parameters = {
            prefix + suffix
            for prefix in ("DocumentIndex", "DocumentEnrichment")
            for suffix in (
                "TaskArn",
                "TaskRoleArn",
                "ExecutionRoleArn",
                "QueueUrl",
                "QueueArn",
            )
        } | {prefix + "MemoryMiB" for prefix in WORKERS}
        if (
            set(overrides)
            - set(actual)
            - (new_parameters if stage == "revisions" else set())
        ):
            raise ValueError("Unknown registration parameter")
        if expanding and (
            actual.get("Enabled") != "false" or overrides.get("Enabled") != "false"
        ):
            raise ValueError(
                "Registration expansion requires acknowledged paused admission"
            )
        template = (
            {
                "TemplateBody": (
                    Path(__file__).resolve().parents[1]
                    / "deploy/personal/background.yml"
                ).read_text()
            }
            if stage == "revisions"
            else {"UsePreviousTemplate": True}
        )
        planned_parameters = actual | overrides
        if stage == "revisions" and not new_parameters <= set(planned_parameters):
            raise ValueError(
                "Revision update must include complete stage and memory parameters"
            )
        try:
            change = self.cf.describe_change_set(
                StackName=BACKGROUND, ChangeSetName=name
            )
        except ClientError as exc:
            if "does not exist" not in str(exc):
                raise
            result = self.cf.create_change_set(
                StackName=BACKGROUND,
                ChangeSetName=name,
                ChangeSetType="UPDATE",
                **template,
                Description=f"product-release:{self.operation}:{stage}",
                Parameters=[
                    {"ParameterKey": k, "ParameterValue": v}
                    for k, v in planned_parameters.items()
                ],
                Capabilities=["CAPABILITY_NAMED_IAM"],
                RoleARN=ROLE,
            )
            for _ in range(60):
                change = self.cf.describe_change_set(ChangeSetName=result["Id"])
                if change["Status"] not in {"CREATE_PENDING", "CREATE_IN_PROGRESS"}:
                    break
                time.sleep(5)
        if (
            change["Status"] != "CREATE_COMPLETE"
            or change["ExecutionStatus"] != "AVAILABLE"
        ):
            raise ValueError("Registration change set is not executable")
        guard_registration_change(change, expanding=expanding)
        planned = {p["ParameterKey"]: p["ParameterValue"] for p in change["Parameters"]}
        if planned != actual | overrides:
            raise ValueError("Registration plan no longer matches live configuration")
        print(
            json.dumps(
                {
                    "registration_change_set": change["ChangeSetId"],
                    "stage": stage,
                    "changes": [
                        x["ResourceChange"]["LogicalResourceId"]
                        for x in change["Changes"]
                    ],
                }
            ),
            flush=True,
        )
        self.cf.execute_change_set(ChangeSetName=change["ChangeSetId"])
        self.wait_stack(BACKGROUND)

    def wait_ack(self) -> None:
        active_names = registration_names(
            {
                p["ParameterKey"]: p["ParameterValue"]
                for p in self.stack(BACKGROUND)["Parameters"]
            }
        )
        parameters = self.ssm.get_parameters(
            Names=[PREFIX + n for n in sorted(active_names)]
        )
        if parameters.get("InvalidParameters") or len(parameters["Parameters"]) != len(
            active_names
        ):
            raise ValueError("Product registration missing")
        expected = {}
        for p in parameters["Parameters"]:
            value = json.loads(p["Value"])
            expected[value["name"]] = {
                "parameter_version": p["Version"],
                "enabled": value["enabled"],
                "task_definition": value["task_definition"],
            }
        for _ in range(60):
            raw = self.ssm.get_parameter(
                Name="/sanchezcloud/personal/admission-status"
            )["Parameter"]["Value"]
            if acknowledged(json.loads(raw), expected, time.time()):
                return
            time.sleep(10)
        raise TimeoutError(
            "Controller did not acknowledge registration versions; do not proceed"
        )

    def wait_drained(self) -> None:
        for _ in range(120):
            arns = set()
            # STOPPING tasks can already have desiredStatus=STOPPED. Both lists are required.
            for status in ("RUNNING", "STOPPED"):
                for p in self.ecs.get_paginator("list_tasks").paginate(
                    cluster=CLUSTER, desiredStatus=status
                ):
                    arns.update(p["taskArns"])
            tasks = []
            ordered = sorted(arns)
            for start in range(0, len(ordered), 100):
                result = self.ecs.describe_tasks(
                    cluster=CLUSTER, tasks=ordered[start : start + 100]
                )
                if result.get("failures"):
                    raise RuntimeError("Cannot prove task termination")
                tasks.extend(result["tasks"])
            if not unsettled(tasks, NAMES):
                return
            time.sleep(10)
        raise TimeoutError(
            "Product worker is still active; paused release can be resumed"
        )

    def revisions(self) -> dict:
        from personal_deployment import LIMITS

        outputs = {
            x["OutputKey"]: x["OutputValue"] for x in self.stack(RUNTIME)["Outputs"]
        }
        result = {}
        for name, queue in WORKERS.items():
            memory = LIMITS[queue + "-worker"][2] + 64
            arn = outputs[name + "WorkerTaskDefinition"]
            task = self.ecs.describe_task_definition(taskDefinition=arn)[
                "taskDefinition"
            ]
            if (
                task.get("requiresCompatibilities") != ["EC2"]
                or sum(c.get("memory", 0) for c in task["containerDefinitions"])
                != memory
                or any(not c.get("memory") for c in task["containerDefinitions"])
                or task.get("memory") is not None
                or task.get("cpu") is not None
            ):
                raise ValueError(
                    "Worker does not satisfy admitted memory and launch contract"
                )
            for field in ("taskRoleArn", "executionRoleArn"):
                if not task[field].startswith(
                    f"arn:aws:iam::{ACCOUNT}:role/SanchezCloudScholens"
                ):
                    raise ValueError("Foreign worker role")
            result.update(
                {
                    name + "TaskArn": arn,
                    name + "TaskRoleArn": task["taskRoleArn"],
                    name + "ExecutionRoleArn": task["executionRoleArn"],
                    name + "MemoryMiB": str(memory),
                }
            )
            worker = next(
                c
                for c in task["containerDefinitions"]
                if c["name"] == queue + "-worker"
            )
            env = {e["name"]: e["value"] for e in worker["environment"]}
            url = env["SQS_" + queue.upper().replace("-", "_") + "_QUEUE_URL"]
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != f"sqs.{REGION}.amazonaws.com"
                or parsed.path != f"/{ACCOUNT}/scholens-preview-{queue}"
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Foreign worker queue")
            result[name + "QueueUrl"] = url
            result[name + "QueueArn"] = (
                f"arn:aws:sqs:{REGION}:{ACCOUNT}:scholens-preview-{queue}"
            )
        return result

    def run(self) -> None:
        if self.read("complete"):
            print(
                json.dumps({"operation": self.operation, "status": "already_applied"})
            )
            return
        context = self.read("start")
        if context is None:
            state = self.stack(BACKGROUND)
            if state["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
                raise ValueError("Background stack must be stable before a release")
            enabled = next(
                p["ParameterValue"]
                for p in state["Parameters"]
                if p["ParameterKey"] == "Enabled"
            )
            context = {"change_set": self.arn, "restore_enabled": enabled}
            self.record("start", context)
        if context["change_set"] != self.arn:
            raise ValueError("Wrong release checkpoint")
        if self.read("runtime") is None:
            self.change_background("pause", {"Enabled": "false"})
            self.wait_ack()
            self.wait_drained()
            self.record("drained", {"change_set": self.arn})
            change = self.cf.describe_change_set(ChangeSetName=self.arn)
            if change["ExecutionStatus"] == "AVAILABLE":
                self.cf.execute_change_set(ChangeSetName=self.arn)
            elif change["ExecutionStatus"] not in {
                "EXECUTE_IN_PROGRESS",
                "EXECUTE_COMPLETE",
            }:
                raise ValueError("Runtime plan is no longer executable")
            self.wait_stack(RUNTIME)
            self.record("runtime", {"change_set": self.arn})
        if self.read("revisions") is None:
            revisions = self.revisions()
            self.change_background("revisions", revisions | {"Enabled": "false"})
            self.record("revisions", revisions)
        self.change_background("resume", {"Enabled": context["restore_enabled"]})
        self.wait_ack()
        self.record(
            "complete", {"change_set": self.arn, "enabled": context["restore_enabled"]}
        )
        print(json.dumps({"operation": self.operation, "status": "complete"}))
