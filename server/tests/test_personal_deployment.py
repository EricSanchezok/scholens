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
    assert len(services) == 6
    for service in services:
        assert service["LaunchType"] == "EC2"
        assert service["DesiredCount"] == {"Fn::If": ["RunApplication", 1, 0]}
        assert "NetworkConfiguration" not in service
        assert service["DeploymentConfiguration"]["MinimumHealthyPercent"] == 0
        assert service["DeploymentConfiguration"]["MaximumPercent"] == 100


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
            assert task["ContainerDefinitions"][0]["Name"] == "web"
        assert task["NetworkMode"] == "bridge"
        assert task["RequiresCompatibilities"] == ["EC2"]
        assert task["RuntimePlatform"]["CpuArchitecture"] == "ARM64"
        for container in task["ContainerDefinitions"]:
            assert container["Name"] != "adot"
            assert container["MemoryReservation"] <= container["Memory"] <= 1280
            assert not any(
                "DEEPSEEK" in s["Name"] and "KEY" in s["Name"]
                for s in container.get("Secrets", [])
            )
            if container["Name"] in {"web", "tmp-init"}:
                continue
            env = {e["Name"]: e["Value"] for e in container["Environment"]}
            assert env["RUNTIME_DEPLOYMENT_MODE"] == "single-host"
            assert env["AUTH_PG_SSL_ROOT_CERT"] == "/run/trust/private-ca.pem"
            assert env["SSL_CERT_FILE"] == "/run/trust/combined-ca.pem"
            assert (
                env["WEBHOOK_BASE_URL"] == "http://host.personal.svc.sanchezcloud:18000"
            )
            assert env["ENVIRONMENT"] == "production"
    assert len(roles) == len(set(roles))
