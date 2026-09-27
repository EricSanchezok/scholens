"""Rehearsal isolation and resource budget contracts for rendered EC2 templates."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "personal_deployment", ROOT / "scripts/personal_deployment.py"
)
assert spec and spec.loader
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def test_foundation_excludes_managed_compute_and_preserves_durable_storage() -> None:
    template = renderer.render("foundation")
    resources = template["Resources"]
    kinds = {r["Type"] for r in resources.values()}
    assert not any(
        x in kind
        for kind in kinds
        for x in ("ElastiCache", "EC2", "ElasticLoadBalancing")
    )
    for resource in resources.values():
        if resource["Type"] in {
            "AWS::S3::Bucket",
            "AWS::KMS::Key",
            "AWS::SQS::Queue",
            "AWS::SecretsManager::Secret",
        }:
            assert resource["DeletionPolicy"] == "RetainExceptOnCreate"
            assert resource["UpdateReplacePolicy"] == "Retain"
    assert (
        resources["ContentBucket"]["Properties"]["VersioningConfiguration"]["Status"]
        == "Enabled"
    )


def test_preview_uses_separate_oidc_subjects_and_account_guard() -> None:
    template = renderer.render("bootstrap")
    text = json.dumps(template)
    for environment in (
        "personal-preview",
        "personal-image-publish",
        "personal-database",
        "personal-infrastructure",
    ):
        assert f":environment:{environment}" in text
    for old in (
        ":environment:production",
        "/production/",
        "919651863140",
        "sg-0ac42d2a5ddffaddf",
        "task/sanchezcloud-production/",
    ):
        assert old not in text
    for stage in ("foundation", "bootstrap", "runtime"):
        assert renderer.render(stage)["Rules"]["ExpectedAccount"]["Assertions"][0][
            "Assert"
        ] == {"Fn::Equals": [{"Ref": "AWS::AccountId"}, {"Ref": "ExpectedAccountId"}]}


def test_runtime_has_one_ec2_task_per_service_and_stop_before_replace() -> None:
    template = renderer.render("runtime")
    assert template["Parameters"]["ApplicationEnabled"]["Default"] == "false"
    resources = template["Resources"]
    assert not any(
        r["Type"]
        in {"AWS::Scheduler::Schedule", "AWS::ApplicationAutoScaling::ScalableTarget"}
        for r in resources.values()
    )
    services = [
        r["Properties"] for r in resources.values() if r["Type"] == "AWS::ECS::Service"
    ]
    assert len(services) == 9
    for service in services:
        assert service["LaunchType"] == "EC2"
        assert service["DesiredCount"] in (
            {"Fn::If": ["RunApplication", 1, 0]},
            {"Fn::If": ["RunResidentBackground", 1, 0]},
            {"Fn::If": ["RunSharedInference", 1, 0]},
        )
        assert "NetworkConfiguration" not in service
        assert service["DeploymentConfiguration"]["MinimumHealthyPercent"] == 0
        assert service["DeploymentConfiguration"]["MaximumPercent"] == 100


def test_admitted_workers_use_container_bounds_and_do_not_change_resident_chat() -> (
    None
):
    template = renderer.render("runtime")
    assert template["Parameters"]["BackgroundMode"]["Default"] == "resident"
    for name in (
        "Document",
        "DocumentIndex",
        "DocumentEnrichment",
        "Research",
        "Maintenance",
    ):
        task = template["Resources"][name + "WorkerTaskDefinition"]["Properties"]
        assert "Cpu" not in task
        assert "Memory" not in task
        containers = task["ContainerDefinitions"]
        assert all(c["Memory"] >= c["MemoryReservation"] > 0 for c in containers)
        worker = next(c for c in containers if c["Name"].endswith("-worker"))
        env = {e["Name"]: e["Value"] for e in worker["Environment"]}
        assert env["SCHOLENS_WORKER_ONE_SHOT"] == {
            "Fn::If": ["AdmittedBackground", "1", "0"]
        }
    chat = template["Resources"]["ConversationWorkerTaskDefinition"]["Properties"]
    assert "Cpu" not in chat
    assert "SCHOLENS_WORKER_ONE_SHOT" not in json.dumps(chat)


def test_document_stages_have_independent_consumers_queues_and_task_roles() -> None:
    resources = renderer.render("runtime")["Resources"]
    foundation = renderer.render("foundation")["Resources"]
    for prefix, queue in (
        ("DocumentIndex", "document-index"),
        ("DocumentEnrichment", "document-enrichment"),
    ):
        assert (
            foundation[prefix + "Queue"]["Properties"]["QueueName"]
            == "scholens-preview-" + queue
        )
        task = resources[prefix + "WorkerTaskDefinition"]["Properties"]
        worker = task["ContainerDefinitions"][0]
        assert "--queues=" + queue in worker["Command"]
        assert worker["Name"] == queue + "-worker"
        assert task["TaskRoleArn"] == {"Fn::GetAtt": [prefix + "WorkerTaskRole", "Arn"]}
        role = resources[prefix + "WorkerTaskRole"]["Properties"]
        statements = role["Policies"][0]["PolicyDocument"]["Statement"]
        receives = [
            s for s in statements if "sqs:ReceiveMessage" in s.get("Action", [])
        ]
        assert [s["Resource"] for s in receives] == [
            {"Fn::ImportValue": "sanchezcloud-scholens-" + queue + "-queue-arn"}
        ]
        assert resources[prefix + "WorkerService"]["Properties"]["DesiredCount"] == {
            "Fn::If": ["RunResidentBackground", 1, 0]
        }


def test_admission_grant_covers_all_five_exact_workers_and_queue_metrics():
    import yaml

    template = yaml.load(
        (ROOT / "deploy/personal/background.yml").read_text(),
        Loader=renderer.CloudFormationLoader,
    )
    statements = template["Resources"]["AdmissionGrant"]["Properties"][
        "PolicyDocument"
    ]["Statement"]
    actions = {s["Action"]: s["Resource"] for s in statements}
    names = {
        "Document",
        "DocumentIndex",
        "DocumentEnrichment",
        "Research",
        "Maintenance",
    }
    for action, suffixes in (
        ("ecs:RunTask", ("TaskArn",)),
        ("iam:PassRole", ("TaskRoleArn", "ExecutionRoleArn")),
        ("sqs:GetQueueAttributes", ("QueueArn",)),
    ):
        assert {r["Ref"] for r in actions[action]} == {
            n + suffix for n in names for suffix in suffixes
        }


def test_personal_email_requires_explicit_cutover_opt_in() -> None:
    template = renderer.render("runtime")
    parameter = template["Parameters"]["EmailDeliveryEnabled"]
    assert parameter["Default"] == "false"
    assert parameter["AllowedValues"] == ["false", "true"]
    for resource in template["Resources"].values():
        if resource["Type"] != "AWS::ECS::TaskDefinition":
            continue
        for container in resource["Properties"]["ContainerDefinitions"]:
            if container["Name"] in {"web", "tmp-init", "inference", "inference-init"}:
                continue
            env = {item["Name"]: item["Value"] for item in container["Environment"]}
            assert env["SCHOLENS_EMAIL_DELIVERY_ENABLED"] == {
                "Ref": "EmailDeliveryEnabled"
            }


def test_task_roles_limits_tls_and_private_callback_remain_independent() -> None:
    resources = renderer.render("runtime")["Resources"]
    definitions = [
        r["Properties"]
        for r in resources.values()
        if r["Type"] == "AWS::ECS::TaskDefinition"
    ]
    roles = []
    for task in definitions:
        if "TaskRoleArn" in task:
            roles.append(json.dumps(task["TaskRoleArn"]))
        else:
            assert task["ContainerDefinitions"][0]["Name"] in {"web", "inference"}
        expected_network = (
            "none"
            if task["ContainerDefinitions"][0]["Name"] == "inference"
            else "bridge"
        )
        assert task["NetworkMode"] == expected_network
        assert task["RequiresCompatibilities"] == ["EC2"]
        assert task["RuntimePlatform"]["CpuArchitecture"] == "ARM64"
        for container in task["ContainerDefinitions"]:
            assert container["Name"] != "adot"
            assert container["MemoryReservation"] <= container["Memory"] <= 2560
            assert not any(
                "DEEPSEEK" in s["Name"] and "KEY" in s["Name"]
                for s in container.get("Secrets", [])
            )
            if container["Name"] in {"web", "tmp-init", "inference", "inference-init"}:
                continue
            env = {e["Name"]: e["Value"] for e in container["Environment"]}
            if container["Name"].endswith("-worker"):
                assert env["SCHOLENS_WORKER_HEARTBEAT_FILE"] == "/tmp/worker-heartbeat"
                assert container["HealthCheck"]["Command"] == [
                    "CMD",
                    "python",
                    "-m",
                    "scholens_observability.worker_health",
                ]
                assert "/livez" not in json.dumps(container["HealthCheck"])
            if container["Name"] == "maintenance-worker":
                assert container["Memory"] >= 512
            assert env["RUNTIME_DEPLOYMENT_MODE"] == "single-host"
            assert env["AUTH_PG_SSL_ROOT_CERT"] == "/run/trust/private-ca.pem"
            assert env["SSL_CERT_FILE"] == "/run/trust/combined-ca.pem"
            assert (
                env["WEBHOOK_BASE_URL"] == "http://host.personal.svc.sanchezcloud:18000"
            )
            assert env["ENVIRONMENT"] == "production"
    assert len(roles) == len(set(roles))


def test_shared_inference_has_one_owner_and_unprivileged_socket_clients():
    resources = renderer.render("runtime")["Resources"]
    task = resources["InferenceTaskDefinition"]["Properties"]
    assert "TaskRoleArn" not in task
    owner = task["ContainerDefinitions"][0]
    assert owner["Image"] == {"Ref": "ApiImage"}
    assert owner["EntryPoint"] == ["python", "-m", "scholens_ai.inference"]
    assert "Secrets" not in owner
    assert "PortMappings" not in owner
    assert owner["Memory"] == 1024
    assert owner["User"] == "1000:1000"
    for prefix in (
        "Api",
        "ConversationWorker",
        "DocumentWorker",
        "DocumentIndexWorker",
        "DocumentEnrichmentWorker",
    ):
        consumer = resources[prefix + "TaskDefinition"]["Properties"][
            "ContainerDefinitions"
        ][0]
        env = {e["Name"]: e["Value"] for e in consumer["Environment"]}
        assert env["SCHOLENS_EMBEDDING_SOCKET"] == {
            "Fn::If": ["SharedInference", "/run/scholens-inference/model.sock", ""]
        }
        mount = next(
            m for m in consumer["MountPoints"] if m["SourceVolume"] == "inference"
        )
        assert mount["ReadOnly"] is True
        if prefix.startswith("Document"):
            assert consumer["User"] == "65532:1000"


def test_document_rollout_is_explicit_and_defaults_to_consumer_first():
    template = renderer.render("runtime")
    assert template["Parameters"]["DocumentPipelinePercent"]["Default"] == 0
    for name in (
        "DocumentPipelineEnabled",
        "JobResultInboxEnabled",
        "JobDispatchFairnessEnabled",
    ):
        assert template["Parameters"][name]["Default"] == "false"
    api = template["Resources"]["ApiTaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]
    env = {e["Name"]: e["Value"] for e in api["Environment"]}
    assert env["DOCUMENT_PIPELINE_PERCENT"] == {"Ref": "DocumentPipelinePercent"}
    assert env["JOB_RESULT_INBOX_ENABLED"] == {"Ref": "JobResultInboxEnabled"}
    assert "DocumentStageConsumers" in template["Rules"]


def test_rollout_planning_preserves_percent_and_keeps_consumers_for_pause(monkeypatch):
    import importlib
    import pytest

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    control = importlib.import_module("personal_control_plane")
    prior = {"DocumentPipelinePercent": "50", "SharedInferenceEnabled": "true"}
    kept = control.processing_overrides(prior, "preserve", shared_inference=True)
    assert kept["DocumentPipelinePercent"] == "50"
    paused = control.processing_overrides(prior, "0", shared_inference=True)
    assert paused["DocumentPipelineEnabled"] == "false"
    assert paused["JobResultInboxEnabled"] == "true"
    assert paused["SharedInferenceEnabled"] == "true"
    with pytest.raises(ValueError, match="rollback"):
        control.processing_overrides(prior, "0", shared_inference=False)


def test_private_cache_enforces_tls_separate_acls_and_no_aws_runtime_role() -> None:
    import yaml

    root = ROOT / "deploy/personal/valkey"
    template = yaml.load(
        (root / "runtime.yml").read_text(), Loader=renderer.CloudFormationLoader
    )
    task = template["Resources"]["CacheTask"]["Properties"]
    assert "TaskRoleArn" not in task
    assert task["NetworkMode"] == "bridge"
    assert template["Parameters"]["CacheEnabled"]["Default"] == "false"
    container = task["ContainerDefinitions"][0]
    assert container["ReadonlyRootFilesystem"]
    assert container["User"] == "999:999"
    assert container["Memory"] == 384
    config = (root / "valkey.conf").read_text()
    assert "\nport 0\n" in config
    assert "tls-port 6380" in config
    assert "maxmemory-policy noeviction" in config
    bootstrap = (root / "start.sh").read_text()
    assert "user default off" in bootstrap
    assert "~scholens:pdf-parse:*" in bootstrap
    assert "~scholens:conversation-events:*" in bootstrap
    assert "unset CACHE_API_PASSWORD CACHE_JOBS_PASSWORD" in bootstrap
    assert "--requirepass" not in bootstrap


def test_control_plane_rejects_foreign_destinations(monkeypatch) -> None:
    import importlib
    import pytest

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    control = importlib.import_module("personal_control_plane")
    for account, region in (
        ("919651863140", "ap-south-2"),
        ("669409472143", "ap-southeast-1"),
    ):
        with pytest.raises(ValueError):
            control.guard_destination(account, region)


def test_control_plane_rejects_destructive_changes_and_stale_reviews(
    monkeypatch,
) -> None:
    import importlib
    import pytest

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    control = importlib.import_module("personal_control_plane")
    base = {
        "StackName": control.STACKS["runtime"],
        "Status": "CREATE_COMPLETE",
        "Description": "personal:runtime:reviewed",
    }
    for action, replacement, kind in (
        ("Remove", "False", "AWS::ECS::Service"),
        ("Modify", "True", "AWS::S3::Bucket"),
        ("Modify", "Conditional", "AWS::IAM::Role"),
        ("Add", "False", "AWS::EC2::NatGateway"),
    ):
        change = dict(
            base,
            Changes=[
                {
                    "ResourceChange": {
                        "Action": action,
                        "Replacement": replacement,
                        "ResourceType": kind,
                    }
                }
            ],
        )
        with pytest.raises(ValueError):
            control.guard_change(change, "runtime", "reviewed")
    with pytest.raises(ValueError):
        control.guard_change(base, "runtime", "different")
    with pytest.raises(ValueError):
        control.guard_change(
            dict(base, StackName="old-production"), "runtime", "reviewed"
        )
    control.guard_change(
        dict(
            base,
            Changes=[
                {
                    "ResourceChange": {
                        "Action": "Modify",
                        "Replacement": "True",
                        "ResourceType": "AWS::ECS::TaskDefinition",
                    }
                }
            ],
        ),
        "runtime",
        "reviewed",
    )


def test_personal_manual_workflows_preserve_isolation_and_migration_proofs() -> None:
    database = (ROOT / ".github/workflows/personal-database.yml").read_text()
    assert "environment: personal-database" in database
    assert "--launch-type EC2" in database
    assert "--network-configuration" not in database
    assert "--cluster sanchezcloud-production" not in database
    assert "--expected-platform linux/arm64" in database
    assert "SCHOLENS_MIGRATION_PROOF=" in database
    assert "create-migration-attestation" in database
    for name in ("personal-infrastructure", "personal-preview"):
        workflow = (ROOT / f".github/workflows/{name}.yml").read_text()
        assert f"environment: {name}" in workflow
        assert "options: [plan, apply]" in workflow
        assert "scholens-personal-control-plane" in workflow
        assert 'allowed-account-ids: "669409472143"' in workflow


def test_measured_parser_budget_requires_owner_and_followup_stages_use_batch_lane():
    import yaml

    runtime = renderer.render("runtime")
    task = runtime["Resources"]["DocumentWorkerTaskDefinition"]["Properties"]
    worker = next(
        c for c in task["ContainerDefinitions"] if c["Name"] == "document-worker"
    )
    assert worker["Memory"] == 1280
    assert "EnabledApplicationRequiresSharedInference" in runtime["Rules"]
    registrations = yaml.load(
        (ROOT / "deploy/personal/background.yml").read_text(),
        Loader=renderer.CloudFormationLoader,
    )
    for name, resource in registrations["Resources"].items():
        if resource["Type"] != "AWS::SSM::Parameter":
            continue
        value = resource["Properties"]["Value"]["Fn::Sub"]
        assert '"priority":2' not in value  # Platform permits only 0 or 1.
        expected = (
            "batch"
            if name in {"DocumentIndexRegistration", "DocumentEnrichmentRegistration"}
            else "interactive"
        )
        assert f'"lane":"{expected}"' in value
