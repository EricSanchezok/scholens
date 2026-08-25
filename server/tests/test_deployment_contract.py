"""Static contracts for the production deployment package."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
ECS = ROOT / "deploy" / "ecs"
FOUNDATION_INLINE_LIMIT = 48_000


class _CloudFormationLoader(yaml.SafeLoader):
    pass


def _cloudformation_tag(loader, suffix: str, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    if suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    key = suffix if suffix in {"Ref", "Condition"} else f"Fn::{suffix}"
    return {key: value}


_CloudFormationLoader.add_multi_constructor("!", _cloudformation_tag)


def load_template(name: str) -> dict[str, object]:
    template = yaml.load(
        (ECS / name).read_text(encoding="utf-8"),
        Loader=_CloudFormationLoader,
    )
    assert isinstance(template, dict)
    return template


def test_foundation_fits_cloudformation_inline_bootstrap_limit() -> None:
    for name in (
        "scholens-foundation-bootstrap.yml",
        "scholens-foundation.yml",
    ):
        assert len((ECS / name).read_bytes()) < FOUNDATION_INLINE_LIMIT


def test_foundation_inline_role_policies_fit_iam_aggregate_quota() -> None:
    for template_name in (
        "scholens-foundation-bootstrap.yml",
        "scholens-foundation.yml",
    ):
        resources = load_template(template_name)["Resources"]
        for name, resource in resources.items():
            if resource["Type"] != "AWS::IAM::Role":
                continue
            policies = resource.get("Properties", {}).get("Policies", [])
            aggregate = sum(
                len(json.dumps(policy["PolicyDocument"], separators=(",", ":")))
                for policy in policies
            )
            assert aggregate <= 10_240, (
                f"{template_name}:{name} inline policies use {aggregate} bytes"
            )


def test_bootstrap_managed_policies_fit_iam_document_quota() -> None:
    resources = load_template("scholens-foundation-bootstrap.yml")["Resources"]
    managed_policies = {
        name: resource
        for name, resource in resources.items()
        if resource["Type"] == "AWS::IAM::ManagedPolicy"
    }
    assert {
        "RuntimeIamControlPolicy",
        "RuntimeComputePolicy",
        "RuntimeOperationsPolicy",
    } <= set(managed_policies)
    for name, resource in managed_policies.items():
        size = len(
            json.dumps(
                resource["Properties"]["PolicyDocument"],
                separators=(",", ":"),
            )
        )
        assert size <= 6_144, f"{name} managed policy uses {size} characters"


def test_foundation_owns_retained_data_planes_and_immutable_images() -> None:
    template = load_template("scholens-foundation.yml")
    resources = template["Resources"]
    assert isinstance(resources, dict)

    retained_types = {
        "AWS::ECR::Repository",
        "AWS::ElastiCache::ServerlessCache",
        "AWS::KMS::Key",
        "AWS::S3::Bucket",
        "AWS::SecretsManager::Secret",
        "AWS::SQS::Queue",
    }
    for resource in resources.values():
        if resource["Type"] in retained_types:
            assert resource["DeletionPolicy"] == "RetainExceptOnCreate"
            assert resource["UpdateReplacePolicy"] == "Retain"

    repositories = [
        resource
        for resource in resources.values()
        if resource["Type"] == "AWS::ECR::Repository"
    ]
    assert len(repositories) == 3
    assert all(
        repo["Properties"]["ImageTagMutability"] == "IMMUTABLE" for repo in repositories
    )

    for name in ("DocumentQueue", "ResearchQueue", "MaintenanceQueue"):
        queue = resources[name]["Properties"]
        assert queue["VisibilityTimeout"] == 2700
        assert queue["MessageRetentionPeriod"] == 1209600
        assert queue["RedrivePolicy"]["maxReceiveCount"] == 5
    conversation_queue = resources["ConversationQueue"]["Properties"]
    assert conversation_queue["VisibilityTimeout"] == 3600
    assert conversation_queue["MessageRetentionPeriod"] == 1209600
    assert conversation_queue["RedrivePolicy"]["maxReceiveCount"] == 5

    cache = resources["Cache"]["Properties"]
    assert cache["Engine"] == "valkey"
    assert cache["UserGroupId"] == {"Ref": "CacheUserGroup"}
    assert cache["DailySnapshotTime"] == "18:00"
    assert re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", cache["DailySnapshotTime"])

    api_cache_access = set(
        resources["ApiCacheUser"]["Properties"]["AccessString"].split()
    )
    assert api_cache_access == {
        "on",
        "~scholens:rate:*",
        "~scholens:concurrency:*",
        "~scholens:translation:*",
        "~scholens:conversation-events:*",
        "+@all",
        "-@dangerous",
    }
    jobs_cache_access = set(
        resources["JobsCacheUser"]["Properties"]["AccessString"].split()
    )
    assert jobs_cache_access == {
        "on",
        "~scholens:pdf-parse:*",
        "+@all",
        "-@dangerous",
    }

    release = resources["ReleaseBucket"]["Properties"]
    assert release["ObjectLockEnabled"] is True
    assert release["ObjectLockConfiguration"] == {
        "ObjectLockEnabled": "Enabled",
        "Rule": {"DefaultRetention": {"Mode": "COMPLIANCE", "Days": 365}},
    }
    lifecycle = {
        rule["Id"]: rule for rule in release["LifecycleConfiguration"]["Rules"]
    }
    assert lifecycle["ExpireCloudFormationArtifacts"]["ExpirationInDays"] == 365
    assert lifecycle["ExpireSourceMaps"]["ExpirationInDays"] == 365
    assert lifecycle["ExpireSourceMaps"]["NoncurrentVersionExpiration"] == {
        "NoncurrentDays": 365
    }

    content = resources["ContentBucket"]["Properties"]
    content_lifecycle = {
        rule["Id"]: rule for rule in content["LifecycleConfiguration"]["Rules"]
    }
    for name, prefix in (
        ("ExpireStagedPaperUploads", "uploads/"),
        ("ExpireStagedZoteroImports", "zotero-imports/"),
    ):
        assert content_lifecycle[name] == {
            "Id": name,
            "Status": "Enabled",
            "Prefix": prefix,
            "ExpirationInDays": 2,
            "NoncurrentVersionExpiration": {"NoncurrentDays": 1},
        }


def test_bucket_policies_reject_only_explicit_wrong_encryption_headers() -> None:
    resources = load_template("scholens-foundation.yml")["Resources"]
    contracts = (
        ("ReleaseBucketPolicy", "ReleaseBucket", "ConfigurationKey"),
        ("ContentBucketPolicy", "ContentBucket", "ContentKey"),
        ("DiagnosticBucketPolicy", "DiagnosticBucket", "DiagnosticKey"),
    )
    for policy_name, bucket_name, key_name in contracts:
        statements = resources[policy_name]["Properties"]["PolicyDocument"]["Statement"]
        by_sid = {statement["Sid"]: statement for statement in statements}
        algorithm = by_sid["DenyExplicitNonKmsEncryption"]
        assert algorithm["Action"] == "s3:PutObject"
        assert algorithm["Resource"] == {"Fn::Sub": f"${{{bucket_name}.Arn}}/*"}
        assert algorithm["Condition"] == {
            "Null": {"s3:x-amz-server-side-encryption": "false"},
            "StringNotEquals": {"s3:x-amz-server-side-encryption": "aws:kms"},
        }
        wrong_key = by_sid["DenyExplicitWrongKmsKey"]
        assert wrong_key["Condition"]["Null"] == {
            "s3:x-amz-server-side-encryption-aws-kms-key-id": "false"
        }
        assert wrong_key["Condition"]["StringNotEquals"] == {
            "s3:x-amz-server-side-encryption-aws-kms-key-id": {
                "Fn::GetAtt": [key_name, "Arn"]
            }
        }


def _policy_statements(resource: dict[str, object]) -> list[dict[str, object]]:
    policies = resource["Properties"]["Policies"]
    return [
        statement
        for policy in policies
        for statement in policy["PolicyDocument"]["Statement"]
    ]


def _actions(statement: dict[str, object]) -> set[str]:
    value = statement["Action"]
    return {value} if isinstance(value, str) else set(value)


def test_bootstrap_roles_enforce_immutable_release_and_scoped_secrets() -> None:
    resources = load_template("scholens-foundation-bootstrap.yml")["Resources"]
    publish = _policy_statements(resources["PublishRole"])
    production = _policy_statements(resources["ProductionDeployRole"])
    database = _policy_statements(resources["DatabaseDeployRole"])
    execution = _policy_statements(resources["TaskExecutionRole"])

    assert all(
        "cloudformation:DeleteStack" not in _actions(item) for item in production
    )
    assert all("s3:BypassGovernanceRetention" not in _actions(item) for item in publish)
    publish_put = next(item for item in publish if "s3:PutObject" in _actions(item))
    assert publish_put["Resource"] == [
        {
            "Fn::Sub": (
                "arn:${AWS::Partition}:s3:::sanchezcloud-scholens-releases-"
                "${AWS::AccountId}-${AWS::Region}/releases/*"
            )
        },
        {
            "Fn::Sub": (
                "arn:${AWS::Partition}:s3:::sanchezcloud-scholens-releases-"
                "${AWS::AccountId}-${AWS::Region}/source-maps/*"
            )
        },
    ]
    production_put = next(
        item for item in production if "s3:PutObject" in _actions(item)
    )
    assert "cloudformation/*" in str(production_put["Resource"])
    avatar_simulation = next(
        item for item in production if "iam:SimulatePrincipalPolicy" in _actions(item)
    )
    assert avatar_simulation["Resource"] == {
        "Fn::Sub": (
            "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/"
            "SanchezCloudScholensApiTaskRole"
        )
    }
    database_put = next(item for item in database if "s3:PutObject" in _actions(item))
    assert "migrations/*" in str(database_put["Resource"])
    database_describe_task_definition = next(
        item for item in database if "ecs:DescribeTaskDefinition" in _actions(item)
    )
    assert database_describe_task_definition["Resource"] == "*"
    database_deregister_task_definition = next(
        item for item in database if "ecs:DeregisterTaskDefinition" in _actions(item)
    )
    assert database_deregister_task_definition["Resource"] == "*"
    database_migration_logs = next(
        item for item in database if "logs:GetLogEvents" in _actions(item)
    )
    assert "log-stream:migration/migration/*" in str(
        database_migration_logs["Resource"]
    )
    assert "log-stream:sanchezcloud/migration/*" not in str(
        database_migration_logs["Resource"]
    )
    assert not any(
        "secretsmanager:GetSecretValue" in _actions(item)
        and "production/edge" in str(item["Resource"])
        for item in production
    )
    execution_secret = next(
        item for item in execution if "secretsmanager:GetSecretValue" in _actions(item)
    )
    assert {"Ref": "ScholightMcpDelegationSecretArn"} in execution_secret["Resource"]
    assert "sanchezcloud-scholight-core-secret-arn" not in str(execution)
    scan_actions = {
        "ecr:BatchGetImage",
        "ecr:DescribeImages",
        "ecr:DescribeImageScanFindings",
    }
    for role in (publish, production):
        scan = next(item for item in role if scan_actions <= _actions(item))
        assert len(scan["Resource"]) == 3
        assert all(
            "repository/sanchezcloud-scholens-" in str(value)
            for value in scan["Resource"]
        )


def test_cloudformation_role_has_current_scoped_waf_association_permissions() -> None:
    resources = load_template("scholens-foundation-bootstrap.yml")["Resources"]
    runtime = resources["RuntimeCloudFormationServiceRole"]
    assert runtime["Properties"]["ManagedPolicyArns"] == [
        {"Ref": "RuntimeIamControlPolicy"},
        {"Ref": "RuntimeComputePolicy"},
        {"Ref": "RuntimeOperationsPolicy"},
    ]
    statements = [
        statement
        for name in (
            "RuntimeIamControlPolicy",
            "RuntimeComputePolicy",
            "RuntimeOperationsPolicy",
        )
        for statement in resources[name]["Properties"]["PolicyDocument"]["Statement"]
    ]
    association_actions = {
        "elasticloadbalancing:CreateWebACLAssociation",
        "elasticloadbalancing:DeleteWebACLAssociation",
        "elasticloadbalancing:GetLoadBalancerWebACL",
    }
    association = next(
        item for item in statements if association_actions <= _actions(item)
    )
    assert association["Resource"] == {
        "Fn::Sub": (
            "arn:${AWS::Partition}:elasticloadbalancing:${AWS::Region}:"
            "${AWS::AccountId}:loadbalancer/app/sanchezcloud-scholens/*"
        )
    }
    describe = next(
        item
        for item in statements
        if "elasticloadbalancing:DescribeWebACLAssociation" in _actions(item)
    )
    assert describe["Resource"] == "*"
    web_acl_actions = {
        "wafv2:AssociateWebACL",
        "wafv2:GetWebACL",
        "wafv2:GetWebACLForResource",
        "wafv2:ListResourcesForWebACL",
    }
    web_acl = next(item for item in statements if web_acl_actions <= _actions(item))
    assert web_acl["Resource"] == {
        "Fn::Sub": (
            "arn:${AWS::Partition}:wafv2:${AWS::Region}:${AWS::AccountId}:"
            "regional/webacl/*/*"
        )
    }
    disassociation = next(
        item for item in statements if "wafv2:DisassociateWebACL" in _actions(item)
    )
    assert disassociation == {
        "Action": "wafv2:DisassociateWebACL",
        "Effect": "Allow",
        "Resource": "*",
    }
    iam_actions = {
        action
        for statement in statements
        for action in _actions(statement)
        if action.startswith("iam:")
    }
    assert "iam:*" not in iam_actions
    runtime_role_names = {
        "SanchezCloudScholensApiTaskRole",
        "SanchezCloudScholensDocumentWorkerTaskRole",
        "SanchezCloudScholensResearchWorkerTaskRole",
        "SanchezCloudScholensMaintenanceWorkerTaskRole",
        "SanchezCloudScholensMigrationTaskRole",
        "SanchezCloudScholensSchedulerTaskRole",
        "SanchezCloudScholensSchedulerInvocationRole",
    }
    role_mutation_actions = {
        "iam:AttachRolePolicy",
        "iam:CreateRole",
        "iam:DetachRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:PutRolePolicy",
        "iam:UpdateAssumeRolePolicy",
    }
    role_mutations = [
        item for item in statements if _actions(item) & role_mutation_actions
    ]
    assert role_mutations
    for statement in role_mutations:
        values = (
            statement["Resource"]
            if isinstance(statement["Resource"], list)
            else [statement["Resource"]]
        )
        assert all(
            any(role_name in str(value) for role_name in runtime_role_names)
            for value in values
        )
        assert "CloudFormationServiceRole" not in str(values)

    create_role = [item for item in statements if "iam:CreateRole" in _actions(item)]
    assert len(create_role) == 2
    assert {
        str(item["Condition"]["ArnEquals"]["iam:PermissionsBoundary"])
        for item in create_role
    } == {
        str({"Ref": "RuntimeTaskPermissionsBoundary"}),
        str({"Ref": "SchedulerInvocationPermissionsBoundary"}),
    }
    pass_roles = [item for item in statements if "iam:PassRole" in _actions(item)]
    assert len(pass_roles) == 2
    assert {
        item["Condition"]["StringEquals"]["iam:PassedToService"] for item in pass_roles
    } == {"ecs-tasks.amazonaws.com", "scheduler.amazonaws.com"}
    assert all(
        "CloudFormationServiceRole" not in str(item["Resource"]) for item in pass_roles
    )
    assert "TaskExecutionRole" in str(pass_roles)

    policy_lifecycle = {
        "iam:CreatePolicy",
        "iam:CreatePolicyVersion",
        "iam:DeletePolicy",
        "iam:DeletePolicyVersion",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "iam:ListPolicyVersions",
        "iam:ListEntitiesForPolicy",
        "iam:SetDefaultPolicyVersion",
    }
    telemetry = next(item for item in statements if policy_lifecycle <= _actions(item))
    assert telemetry["Resource"] == {
        "Fn::Sub": (
            "arn:${AWS::Partition}:iam::${AWS::AccountId}:policy/"
            "SanchezCloudScholensTelemetry"
        )
    }

    iam_statements = [
        item
        for item in statements
        if any(action.startswith("iam:") for action in _actions(item))
    ]
    for item in iam_statements:
        if item["Resource"] == "*":
            assert _actions(item) <= {"iam:ListPolicies", "iam:ListRoles"}
            continue
        if "iam:CreateServiceLinkedRole" in _actions(item):
            assert "role/aws-service-role/*" in str(item["Resource"])
            assert "iam:AWSServiceName" in str(item["Condition"])
        elif any("Role" in action for action in _actions(item)):
            assert "role/SanchezCloudScholens" in str(item["Resource"])

    for service in ("secretsmanager:",):
        scoped = [
            item
            for item in statements
            if any(action.startswith(service) for action in _actions(item))
        ]
        assert scoped
        for item in scoped:
            if _actions(item) == {"secretsmanager:GetRandomPassword"}:
                assert item["Resource"] == "*"
            else:
                assert item["Resource"] != "*"

    broad_actions = {
        action
        for item in statements
        if item["Resource"] == "*"
        for action in _actions(item)
    }
    assert not any(action.startswith(("ecr:", "s3:")) for action in broad_actions)
    assert {action for action in broad_actions if action.startswith("iam:")} <= {
        "iam:ListPolicies",
        "iam:ListRoles",
    }
    assert not any(action.startswith("secretsmanager:") for action in broad_actions)
    assert "iam:DeleteRolePermissionsBoundary" not in iam_actions


def test_runtime_role_scopes_shared_rds_alarm_lifecycle_symmetrically() -> None:
    resources = load_template("scholens-foundation-bootstrap.yml")["Resources"]
    runtime = load_template("scholens-production.yml")
    alarm_name = runtime["Resources"]["DatabaseConnectionsAlarm"]["Properties"][
        "AlarmName"
    ]
    assert alarm_name == "sanchezcloud-shared-rds-connections-near-capacity"
    statements = resources["RuntimeOperationsPolicy"]["Properties"]["PolicyDocument"][
        "Statement"
    ]
    alarm = next(
        item for item in statements if "cloudwatch:PutMetricAlarm" in _actions(item)
    )

    assert {
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:DeleteAlarms",
    } <= _actions(alarm)
    assert alarm["Resource"] == [
        {
            "Fn::Sub": (
                "arn:${AWS::Partition}:cloudwatch:${AWS::Region}:"
                "${AWS::AccountId}:alarm:sanchezcloud-scholens-*"
            )
        },
        {
            "Fn::Sub": (
                "arn:${AWS::Partition}:cloudwatch:${AWS::Region}:"
                "${AWS::AccountId}:alarm:"
                "sanchezcloud-shared-rds-connections-near-capacity"
            )
        },
    ]


def test_runtime_role_limits_aws_managed_rule_set_validation_to_web_acl_writes() -> (
    None
):
    resources = load_template("scholens-foundation-bootstrap.yml")["Resources"]
    statements = resources["RuntimeOperationsPolicy"]["Properties"]["PolicyDocument"][
        "Statement"
    ]
    managed_rule_set_arn = (
        "arn:${AWS::Partition}:wafv2:${AWS::Region}:${AWS::AccountId}:"
        "regional/managedruleset/*/*"
    )
    managed_rule_set_statements = [
        item for item in statements if "managedruleset/" in str(item["Resource"])
    ]

    assert managed_rule_set_statements == [
        {
            "Action": ["wafv2:CreateWebACL", "wafv2:UpdateWebACL"],
            "Effect": "Allow",
            "Resource": {"Fn::Sub": managed_rule_set_arn},
        }
    ]


def test_runtime_role_scopes_scheduler_lifecycle_to_declared_schedule() -> None:
    bootstrap = load_template("scholens-foundation-bootstrap.yml")["Resources"]
    runtime = load_template("scholens-production.yml")
    schedule_name = runtime["Resources"]["ZoteroSchedule"]["Properties"]["Name"]
    schedule_expression = runtime["Resources"]["ZoteroSchedule"]["Properties"][
        "ScheduleExpression"
    ]
    statements = bootstrap["RuntimeOperationsPolicy"]["Properties"]["PolicyDocument"][
        "Statement"
    ]
    scheduler = next(
        item for item in statements if "scheduler:CreateSchedule" in _actions(item)
    )

    assert schedule_name == "sanchezcloud-scholens-zotero-sync"
    assert schedule_expression == "rate(1 hour)"
    assert scheduler["Resource"] == {
        "Fn::Sub": (
            "arn:${AWS::Partition}:scheduler:${AWS::Region}:${AWS::AccountId}:"
            f"schedule/default/{schedule_name}"
        )
    }


def test_foundation_and_runtime_cloudformation_roles_are_split_and_complete() -> None:
    foundation = load_template("scholens-foundation.yml")
    bootstrap = load_template("scholens-foundation-bootstrap.yml")
    resources = foundation["Resources"]
    bootstrap_resources = bootstrap["Resources"]

    assert not any(
        resource["Type"].startswith("AWS::IAM::") for resource in resources.values()
    )

    runtime = bootstrap_resources["RuntimeCloudFormationServiceRole"]
    assert runtime["Properties"]["RoleName"] == (
        "SanchezCloudScholensRuntimeCloudFormationServiceRole"
    )
    assert "FoundationCloudFormationServiceRole" not in str(runtime)

    production_pass = next(
        item
        for item in _policy_statements(bootstrap_resources["ProductionDeployRole"])
        if "iam:PassRole" in _actions(item)
    )
    assert production_pass["Resource"] == {
        "Fn::GetAtt": ["RuntimeCloudFormationServiceRole", "Arn"]
    }
    infrastructure_pass = next(
        item
        for item in _policy_statements(bootstrap_resources["InfrastructureDeployRole"])
        if "iam:PassRole" in _actions(item)
    )
    assert infrastructure_pass["Resource"] == {
        "Fn::GetAtt": ["FoundationCloudFormationServiceRole", "Arn"]
    }

    bootstrap_role = bootstrap_resources["FoundationCloudFormationServiceRole"]
    assert bootstrap_role["Properties"]["RoleName"] == (
        "SanchezCloudScholensFoundationCloudFormationServiceRole"
    )
    bootstrap_statements = _policy_statements(bootstrap_role)
    bootstrap_iam_actions = {
        action
        for item in bootstrap_statements
        for action in _actions(item)
        if action.startswith("iam:")
    }
    assert bootstrap_iam_actions == {"iam:CreateServiceLinkedRole"}
    service_linked = next(
        item
        for item in bootstrap_statements
        if "iam:CreateServiceLinkedRole" in _actions(item)
    )
    assert "elasticache.amazonaws.com" in str(service_linked["Resource"])
    assert service_linked["Condition"] == {
        "StringEquals": {"iam:AWSServiceName": "elasticache.amazonaws.com"}
    }
    forbidden_iam_mutations = {
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:DeleteRolePermissionsBoundary",
        "iam:DeleteRolePolicy",
        "iam:PassRole",
        "iam:PutRolePermissionsBoundary",
        "iam:PutRolePolicy",
        "iam:UpdateAssumeRolePolicy",
        "iam:UpdateRole",
        "iam:UpdateRoleDescription",
    }
    assert not (bootstrap_iam_actions & forbidden_iam_mutations)

    create_security_group = next(
        item
        for item in bootstrap_statements
        if "ec2:CreateSecurityGroup" in _actions(item)
    )
    assert "Condition" not in create_security_group
    assert create_security_group["Resource"] == [
        {
            "Fn::Sub": [
                "arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:vpc/${VpcId}",
                {"VpcId": {"Fn::ImportValue": "sanchezcloud-production-vpc-id"}},
            ]
        },
        {
            "Fn::Sub": (
                "arn:${AWS::Partition}:ec2:${AWS::Region}:"
                "${AWS::AccountId}:security-group/*"
            )
        },
    ]
    schedule_key_deletion = next(
        item
        for item in bootstrap_statements
        if "kms:ScheduleKeyDeletion" in _actions(item)
    )
    assert schedule_key_deletion["Condition"] == {
        "StringEquals": {
            "aws:ResourceTag/ManagedBy": "CloudFormation",
            "aws:ResourceTag/Product": "Scholens",
        }
    }

    bucket_policy_delete = next(
        item
        for item in bootstrap_statements
        if "s3:DeleteBucketPolicy" in _actions(item)
    )
    assert bucket_policy_delete["Resource"] == {
        "Fn::Sub": "arn:${AWS::Partition}:s3:::sanchezcloud-scholens-*"
    }
    serverless_cache = next(
        item
        for item in bootstrap_statements
        if "elasticache:CreateServerlessCache" in _actions(item)
    )
    assert {
        "Fn::Sub": (
            "arn:${AWS::Partition}:elasticache:${AWS::Region}:"
            "${AWS::AccountId}:serverlesscache:sanchezcloud-scholens"
        )
    } in serverless_cache["Resource"]

    production_vpc_arn = {
        "Fn::Sub": [
            "arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:vpc/${VpcId}",
            {"VpcId": {"Fn::ImportValue": "sanchezcloud-production-vpc-id"}},
        ]
    }
    create_vpc_endpoint = next(
        item
        for item in bootstrap_statements
        if "ec2:CreateVpcEndpoint" in _actions(item)
    )
    assert create_vpc_endpoint["Resource"] == [
        production_vpc_arn,
        {
            "Fn::Sub": [
                "arn:${AWS::Partition}:ec2:${AWS::Region}:"
                "${AWS::AccountId}:subnet/${SubnetId}",
                {
                    "SubnetId": {
                        "Fn::ImportValue": "sanchezcloud-production-private-subnet-1"
                    }
                },
            ]
        },
        {
            "Fn::Sub": [
                "arn:${AWS::Partition}:ec2:${AWS::Region}:"
                "${AWS::AccountId}:subnet/${SubnetId}",
                {
                    "SubnetId": {
                        "Fn::ImportValue": "sanchezcloud-production-private-subnet-2"
                    }
                },
            ]
        },
        {
            "Fn::Sub": (
                "arn:${AWS::Partition}:ec2:${AWS::Region}:"
                "${AWS::AccountId}:security-group/*"
            )
        },
        {
            "Fn::Sub": (
                "arn:${AWS::Partition}:ec2:${AWS::Region}:"
                "${AWS::AccountId}:vpc-endpoint/*"
            )
        },
    ]
    delete_vpc_endpoint = next(
        item
        for item in bootstrap_statements
        if "ec2:DeleteVpcEndpoints" in _actions(item)
    )
    assert delete_vpc_endpoint["Condition"] == {
        "ArnEquals": {"ec2:Vpc": production_vpc_arn}
    }
    tag_vpc_endpoint = next(
        item
        for item in bootstrap_statements
        if "ec2:CreateTags" in _actions(item)
        and "vpc-endpoint/*" in str(item["Resource"])
    )
    assert tag_vpc_endpoint["Condition"] == {
        "StringEquals": {"ec2:CreateAction": "CreateVpcEndpoint"}
    }

    runtime_compute = bootstrap_resources["RuntimeComputePolicy"]
    runtime_create_security_group = next(
        item
        for item in runtime_compute["Properties"]["PolicyDocument"]["Statement"]
        if "ec2:CreateSecurityGroup" in _actions(item)
    )
    assert "Condition" not in runtime_create_security_group
    assert (
        runtime_create_security_group["Resource"] == create_security_group["Resource"]
    )

    admin_owned_roles = {
        "FoundationCloudFormationServiceRole",
        "RuntimeCloudFormationServiceRole",
        "TaskExecutionRole",
        "PublishRole",
        "ProductionDeployRole",
        "DatabaseDeployRole",
        "InfrastructureDeployRole",
        "DiagnosticBreakGlassRole",
    }
    assert admin_owned_roles <= set(bootstrap_resources)
    for name in admin_owned_roles:
        resource = bootstrap_resources[name]
        assert resource["DeletionPolicy"] == "RetainExceptOnCreate"
        assert resource["UpdateReplacePolicy"] == "Retain"

    boundaries = {
        "RuntimeTaskPermissionsBoundary",
        "SchedulerInvocationPermissionsBoundary",
    }
    for name in boundaries:
        resource = bootstrap_resources[name]
        assert resource["Type"] == "AWS::IAM::ManagedPolicy"
        assert resource["DeletionPolicy"] == "RetainExceptOnCreate"
        assert resource["UpdateReplacePolicy"] == "Retain"
        statements = resource["Properties"]["PolicyDocument"]["Statement"]
        assert not any(
            _actions(statement) == {"*"} and statement["Resource"] == "*"
            for statement in statements
        )

    runtime_resources = {
        "TelemetryPolicy",
        "ApiTaskRole",
        "DocumentWorkerTaskRole",
        "ResearchWorkerTaskRole",
        "MaintenanceWorkerTaskRole",
        "MigrationTaskRole",
        "SchedulerTaskRole",
        "SchedulerInvocationRole",
    }
    for name in runtime_resources:
        assert resources.get(name) is None
        resource = load_template("scholens-production.yml")["Resources"][name]
        assert "DeletionPolicy" not in resource
        assert "UpdateReplacePolicy" not in resource


def test_disabled_application_cannot_be_resurrected_by_autoscaling() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    targets = {
        name: resource
        for name, resource in resources.items()
        if resource["Type"] == "AWS::ApplicationAutoScaling::ScalableTarget"
    }
    assert set(targets) == {
        "WebScalableTarget",
        "ApiScalableTarget",
        "ConversationWorkerScalableTarget",
        "DocumentWorkerScalableTarget",
        "ResearchWorkerScalableTarget",
        "MaintenanceWorkerScalableTarget",
    }
    for target in targets.values():
        minimum = target["Properties"]["MinCapacity"]["Fn::If"]
        maximum = target["Properties"]["MaxCapacity"]["Fn::If"]
        assert minimum[0] == maximum[0] == "RunApplication"
        assert minimum[2] == maximum[2] == 0


def test_worker_minimums_and_metric_math_support_scale_to_zero() -> None:
    resources = load_template("scholens-production.yml")["Resources"]

    expected = {
        "Conversation": 1,
        "Document": 1,
        "Research": 0,
        "Maintenance": 0,
    }
    for worker, minimum in expected.items():
        service = resources[f"{worker}WorkerService"]["Properties"]
        target = resources[f"{worker}WorkerScalableTarget"]["Properties"]
        policy = resources[f"{worker}BacklogScaling"]["Properties"][
            "TargetTrackingScalingPolicyConfiguration"
        ]
        expression = next(
            metric["Expression"]
            for metric in policy["CustomizedMetricSpecification"]["Metrics"]
            if metric["Id"] == "backlogpertask"
        )

        assert service["DesiredCount"] == {"Fn::If": ["RunApplication", minimum, 0]}
        assert target["MinCapacity"] == {"Fn::If": ["RunApplication", minimum, 0]}
        assert expression == "backlog/IF(FILL(running,0)<1,1,FILL(running,0))"


def test_conversation_capacity_and_rollout_order_match_latency_slo() -> None:
    resources = load_template("scholens-production.yml")["Resources"]

    service = resources["ConversationWorkerService"]["Properties"]
    assert service["DesiredCount"] == {"Fn::If": ["RunApplication", 1, 0]}

    target = resources["ConversationWorkerScalableTarget"]["Properties"]
    assert target["MinCapacity"] == {"Fn::If": ["RunApplication", 1, 0]}
    assert target["MaxCapacity"] == {"Fn::If": ["RunApplication", 6, 0]}

    tracking = resources["ConversationBacklogScaling"]["Properties"][
        "TargetTrackingScalingPolicyConfiguration"
    ]
    assert tracking["TargetValue"] == 0.25
    assert tracking["ScaleOutCooldown"] == 30
    assert tracking["ScaleInCooldown"] == 900

    age_alarm = resources["ConversationAgeAlarm"]["Properties"]
    assert age_alarm["Namespace"] == "AWS/SQS"
    assert age_alarm["MetricName"] == "ApproximateAgeOfOldestMessage"
    assert age_alarm["Dimensions"] == [
        {"Name": "QueueName", "Value": "scholens-production-conversation"}
    ]
    assert age_alarm["Statistic"] == "Maximum"
    assert age_alarm["Period"] == 60
    assert age_alarm["EvaluationPeriods"] == 1
    assert age_alarm["Threshold"] == 15

    # CloudFormation serializes updates in dependency order, so the API that
    # owns `/start` reaches steady state before the Web that consumes it.
    assert resources["WebService"]["DependsOn"] == ["HttpsListener", "ApiService"]

    dashboard_body = resources["Dashboard"]["Properties"]["DashboardBody"]["Fn::Sub"][0]
    rendered_dashboard = re.sub(r"\$\{[^}]+\}", "fixture", dashboard_body)
    widgets = json.loads(rendered_dashboard)["widgets"]
    by_title = {widget["properties"].get("title"): widget for widget in widgets}
    accept = by_title["Conversation durable accept p95 (ms)"]["properties"]
    claim = by_title["Conversation worker claim age p95 (s)"]["properties"]
    assert accept["stat"] == claim["stat"] == "p95"
    assert accept["metrics"][0] == [
        "Scholens/Production",
        "scholens.conversation.accept.total_duration",
        "status",
        "accepted",
        "generation_kind",
        "initial",
        "OTelLib",
        "scholens",
    ]
    assert claim["metrics"][0] == [
        "Scholens/Production",
        "scholens.conversation.worker.claim_age",
        "generation_kind",
        "initial",
        "OTelLib",
        "scholens",
    ]


def test_unhealthy_target_alarms_use_load_balancer_and_target_group() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    for name, target_group in (
        ("WebUnhealthyTargetsAlarm", "WebTargetGroup"),
        ("ApiUnhealthyTargetsAlarm", "ApiTargetGroup"),
    ):
        alarm = resources[name]["Properties"]
        assert alarm["MetricName"] == "UnHealthyHostCount"
        assert alarm["Statistic"] == "Minimum"
        assert alarm["EvaluationPeriods"] == alarm["DatapointsToAlarm"] == 2
        assert alarm["Dimensions"] == [
            {
                "Name": "LoadBalancer",
                "Value": {"Fn::GetAtt": ["LoadBalancer", "LoadBalancerFullName"]},
            },
            {
                "Name": "TargetGroup",
                "Value": {"Fn::GetAtt": [target_group, "TargetGroupFullName"]},
            },
        ]
    dashboard = str(resources["Dashboard"])
    assert "WebTargetGroupName" in dashboard
    assert "ApiTargetGroupName" in dashboard


def test_api_version_locked_upload_reads_are_allowed_by_role_and_boundary() -> None:
    bootstrap = load_template("scholens-foundation-bootstrap.yml")["Resources"]
    boundary_statements = bootstrap["RuntimeTaskPermissionsBoundary"]["Properties"][
        "PolicyDocument"
    ]["Statement"]
    boundary_version_read = next(
        statement
        for statement in boundary_statements
        if _actions(statement) == {"s3:GetObjectVersion"}
    )
    assert boundary_version_read["Resource"] == {
        "Fn::Sub": (
            "arn:${AWS::Partition}:s3:::sanchezcloud-scholens-content-"
            "${AWS::AccountId}-${AWS::Region}/uploads/*"
        )
    }

    resources = load_template("scholens-production.yml")["Resources"]
    api_version_read = next(
        statement
        for statement in _policy_statements(resources["ApiTaskRole"])
        if _actions(statement) == {"s3:GetObjectVersion"}
    )
    assert api_version_read["Resource"] == {
        "Fn::Sub": [
            "${BucketArn}/uploads/*",
            {
                "BucketArn": {
                    "Fn::ImportValue": "sanchezcloud-scholens-content-bucket-arn"
                }
            },
        ]
    }
    for role_name in (
        "DocumentWorkerTaskRole",
        "ResearchWorkerTaskRole",
        "MaintenanceWorkerTaskRole",
    ):
        assert all(
            "s3:GetObjectVersion" not in _actions(statement)
            for statement in _policy_statements(resources[role_name])
        )

    api_container = next(
        container
        for container in resources["ApiTaskDefinition"]["Properties"][
            "ContainerDefinitions"
        ]
        if container["Name"] == "api"
    )
    api_environment = {
        item["Name"]: item["Value"] for item in api_container["Environment"]
    }
    assert api_environment["S3_KMS_KEY_ID"] == {
        "Fn::ImportValue": "sanchezcloud-scholens-content-key-arn"
    }


def test_shared_avatar_access_is_read_only_and_api_scoped() -> None:
    avatar_prefix = (
        "arn:${AWS::Partition}:s3:::sanchezcloud-account-avatars-"
        "${AWS::AccountId}-${AWS::Region}/auth/avatars/v1/*"
    )
    bootstrap_template = load_template("scholens-foundation-bootstrap.yml")
    bootstrap = bootstrap_template["Resources"]
    avatar_key_pattern = r"^arn:[^:]+:kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-f-]+$"
    assert bootstrap_template["Parameters"]["AvatarKmsKeyArn"] == {
        "AllowedPattern": avatar_key_pattern,
        "Type": "String",
    }
    boundary = bootstrap["RuntimeTaskPermissionsBoundary"]["Properties"][
        "PolicyDocument"
    ]["Statement"]
    boundary_object = next(
        statement
        for statement in boundary
        if statement.get("Resource") == {"Fn::Sub": avatar_prefix}
    )
    assert _actions(boundary_object) == {"s3:GetObject"}

    expected_condition = {
        "StringEquals": {
            "kms:ViaService": {"Fn::Sub": "s3.${AWS::Region}.${AWS::URLSuffix}"}
        },
        "StringLike": {"kms:EncryptionContext:aws:s3:arn": {"Fn::Sub": avatar_prefix}},
    }
    boundary_decrypt = next(
        statement
        for statement in boundary
        if _actions(statement) == {"kms:Decrypt"}
        and statement.get("Condition") == expected_condition
    )
    assert boundary_decrypt["Resource"] == {"Ref": "AvatarKmsKeyArn"}

    production_template = load_template("scholens-production.yml")
    assert production_template["Parameters"]["AvatarKmsKeyArn"] == {
        "AllowedPattern": avatar_key_pattern,
        "Type": "String",
    }
    resources = production_template["Resources"]
    api_statements = _policy_statements(resources["ApiTaskRole"])
    api_object = next(
        statement
        for statement in api_statements
        if statement.get("Resource") == {"Fn::Sub": avatar_prefix}
    )
    assert _actions(api_object) == {"s3:GetObject"}
    api_decrypt = next(
        statement
        for statement in api_statements
        if _actions(statement) == {"kms:Decrypt"}
        and statement.get("Condition") == expected_condition
    )
    assert api_decrypt["Resource"] == {"Ref": "AvatarKmsKeyArn"}
    for role_name in (
        "DocumentWorkerTaskRole",
        "ResearchWorkerTaskRole",
        "MaintenanceWorkerTaskRole",
        "MigrationTaskRole",
        "SchedulerTaskRole",
    ):
        assert "sanchezcloud-account-avatars" not in str(resources[role_name])

    api_container = next(
        container
        for container in resources["ApiTaskDefinition"]["Properties"][
            "ContainerDefinitions"
        ]
        if container["Name"] == "api"
    )
    environment = {item["Name"]: item["Value"] for item in api_container["Environment"]}
    assert environment["SHARED_AVATAR_BUCKET"] == {
        "Fn::Sub": "sanchezcloud-account-avatars-${AWS::AccountId}-${AWS::Region}"
    }
    assert environment["SHARED_AVATAR_URL_TTL_SECONDS"] == "900"

    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    readme = (ECS / "README.md").read_text(encoding="utf-8")
    for deployment_contract in (workflow, readme):
        assert "sanchezcloud-account-center-foundation" in deployment_contract
        assert "Outputs[?OutputKey==`AvatarKmsKeyArn`]" in deployment_contract
    assert 'test "$avatar_kms_key_arn" != None' in workflow
    assert 'test "$avatar_kms_key_arn" != None' in readme
    assert "iam simulate-principal-policy" in workflow
    assert "AllowedByPermissionsBoundary == true" in workflow
    assert "s3:GetObject" in workflow
    assert "kms:Decrypt" in workflow
    assert (
        workflow.count(
            'AvatarKmsKeyArn) parameter_overrides+=("AvatarKmsKeyArn=$AVATAR_KMS_KEY_ARN")'
        )
        == 2
    )
    assert 'AvatarKmsKeyArn="$avatar_kms_key_arn"' in readme


def test_api_and_dependency_failures_have_actionable_alarms_and_dashboard() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    for task_definition, workload in (
        ("ApiTaskDefinition", "api"),
        ("DocumentWorkerTaskDefinition", "document-worker"),
        ("ResearchWorkerTaskDefinition", "research-worker"),
        ("MaintenanceWorkerTaskDefinition", "maintenance-worker"),
    ):
        containers = resources[task_definition]["Properties"]["ContainerDefinitions"]
        container = next(item for item in containers if item["Name"] == workload)
        environment = {item["Name"]: item["Value"] for item in container["Environment"]}
        assert (
            environment["OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE"] == "DELTA"
        )

    recovery_alarm = resources["PdfUnclaimedRecoveryAlarm"]["Properties"]
    assert recovery_alarm["MetricName"] == "scholens.jobs.pdf_unclaimed_recoveries"
    assert recovery_alarm["Threshold"] == 1
    assert recovery_alarm["TreatMissingData"] == "notBreaching"

    target_alarm = resources["ApiTarget5xxAlarm"]["Properties"]
    assert target_alarm["Namespace"] == "AWS/ApplicationELB"
    assert target_alarm["MetricName"] == "HTTPCode_Target_5XX_Count"
    assert target_alarm["Statistic"] == "Sum"
    assert target_alarm["Period"] == 300
    assert target_alarm["Threshold"] == 5
    assert target_alarm["Dimensions"] == [
        {
            "Name": "LoadBalancer",
            "Value": {"Fn::GetAtt": ["LoadBalancer", "LoadBalancerFullName"]},
        },
        {
            "Name": "TargetGroup",
            "Value": {"Fn::GetAtt": ["ApiTargetGroup", "TargetGroupFullName"]},
        },
    ]

    dependency_alarms = {
        "RedisDependencyFailureAlarm": "redis",
        "S3DependencyFailureAlarm": "s3",
    }
    for name, dependency in dependency_alarms.items():
        alarm = resources[name]["Properties"]
        assert alarm["Namespace"] == "Scholens/Production"
        assert alarm["MetricName"] == "scholens.dependency.failures"
        assert alarm["Dimensions"] == [
            {"Name": "dependency", "Value": dependency},
            {"Name": "OTelLib", "Value": "scholens"},
        ]
        assert alarm["Statistic"] == "Sum"
        assert alarm["Period"] == 300
        assert alarm["Threshold"] == 1
        assert alarm["AlarmActions"] == [
            {"Fn::ImportValue": "sanchezcloud-scholens-alert-topic-arn"}
        ]

    diagnostic_alarm = resources["DiagnosticSnapshotWriteFailureAlarm"]["Properties"]
    assert diagnostic_alarm["Namespace"] == "Scholens/Production"
    assert diagnostic_alarm["MetricName"] == "scholens.diagnostic_snapshot.write_failed"
    assert diagnostic_alarm["Dimensions"] == [{"Name": "OTelLib", "Value": "scholens"}]
    assert diagnostic_alarm["Threshold"] == 1

    avatar_alarm = resources["SharedAvatarReadFailureAlarm"]["Properties"]
    assert avatar_alarm["Namespace"] == "Scholens/Production"
    assert avatar_alarm["MetricName"] == "scholens.shared_avatar.read_failed"
    assert avatar_alarm["Dimensions"] == [{"Name": "OTelLib", "Value": "scholens"}]
    assert avatar_alarm["Statistic"] == "Sum"
    assert avatar_alarm["Period"] == 300
    assert avatar_alarm["Threshold"] == 1
    assert avatar_alarm["AlarmActions"] == [
        {"Fn::ImportValue": "sanchezcloud-scholens-alert-topic-arn"}
    ]

    dashboard = str(resources["Dashboard"])
    assert "HTTPCode_Target_5XX_Count" in dashboard
    assert "scholens.dependency.failures" in dashboard
    assert "scholens.shared_avatar.read_failed" in dashboard
    assert "scholens.diagnostic_snapshot.write_failed" in dashboard
    dashboard_body = resources["Dashboard"]["Properties"]["DashboardBody"]["Fn::Sub"][0]
    rendered_dashboard = re.sub(r"\$\{[^}]+\}", "fixture", dashboard_body)
    widgets = json.loads(rendered_dashboard)["widgets"]
    assert len(widgets) == 10
    assert "web_performance" in dashboard_body
    assert "conversation_performance" in dashboard_body
    assert "Conversation feedback and stream p75 / p95" in dashboard_body
    assert "scholens.conversation.worker.claim_age" in dashboard_body
    assert "scholens.conversation.accept.total_duration" in dashboard_body
    assert "primary_content" in dashboard_body


def test_scheduler_and_worker_task_protection_are_cluster_scoped() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    for name in (
        "ApiTaskRole",
        "DocumentWorkerTaskRole",
        "ResearchWorkerTaskRole",
        "MaintenanceWorkerTaskRole",
        "MigrationTaskRole",
        "SchedulerTaskRole",
    ):
        assert resources[name]["Properties"]["PermissionsBoundary"] == {
            "Fn::ImportValue": "sanchezcloud-scholens-runtime-task-boundary-arn"
        }
    assert resources["SchedulerInvocationRole"]["Properties"][
        "PermissionsBoundary"
    ] == {
        "Fn::ImportValue": ("sanchezcloud-scholens-scheduler-invocation-boundary-arn")
    }
    scheduler = _policy_statements(resources["SchedulerInvocationRole"])
    pass_role = next(item for item in scheduler if "iam:PassRole" in _actions(item))
    assert pass_role["Condition"] == {
        "StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}
    }
    for name in (
        "DocumentWorkerTaskRole",
        "ResearchWorkerTaskRole",
        "MaintenanceWorkerTaskRole",
    ):
        statements = _policy_statements(resources[name])
        protection = next(
            item for item in statements if "ecs:UpdateTaskProtection" in _actions(item)
        )
        assert protection["Resource"] == "*"
        assert protection["Condition"] == {
            "ArnEquals": {
                "ecs:cluster": {
                    "Fn::ImportValue": "sanchezcloud-production-cluster-arn"
                }
            }
        }


def test_runtime_uses_private_fargate_services_and_digest_images() -> None:
    template = load_template("scholens-production.yml")
    parameters = template["Parameters"]
    resources = template["Resources"]
    assert isinstance(parameters, dict)
    assert isinstance(resources, dict)

    for parameter in ("WebImage", "ApiImage", "JobsImage"):
        assert "@sha256:" in parameters[parameter]["AllowedPattern"]

    services = {
        name: resource
        for name, resource in resources.items()
        if resource["Type"] == "AWS::ECS::Service"
    }
    assert set(services) == {
        "WebService",
        "ApiService",
        "ConversationWorkerService",
        "DocumentWorkerService",
        "ResearchWorkerService",
        "MaintenanceWorkerService",
    }
    for service in services.values():
        network = service["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]
        assert network["AssignPublicIp"] == "DISABLED"
        assert len(network["Subnets"]) == 2
        assert service["Properties"]["DeploymentConfiguration"][
            "DeploymentCircuitBreaker"
        ] == {"Enable": True, "Rollback": True}

    for name in (
        "ConversationWorkerService",
        "DocumentWorkerService",
        "ResearchWorkerService",
        "MaintenanceWorkerService",
    ):
        providers = services[name]["Properties"]["CapacityProviderStrategy"]
        assert providers == [
            {"CapacityProvider": "FARGATE", "Base": 1, "Weight": 1},
            {"CapacityProvider": "FARGATE_SPOT", "Weight": 3},
        ]
    conversation_task = resources["ConversationWorkerTaskDefinition"]["Properties"]
    assert conversation_task["TaskRoleArn"] == {"Fn::GetAtt": ["ApiTaskRole", "Arn"]}
    conversation_container = next(
        item
        for item in conversation_task["ContainerDefinitions"]
        if item["Name"] == "conversation-worker"
    )
    assert conversation_container["Image"] == {"Ref": "ApiImage"}
    assert conversation_container["Command"] == ["conversation-worker"]
    assert conversation_container["StopTimeout"] == 120

    discovery = resources["ApiDiscoveryService"]
    assert discovery["Type"] == "AWS::ServiceDiscovery::Service"
    assert discovery["Properties"]["DnsConfig"]["DnsRecords"] == [
        {"Type": "A", "TTL": 10}
    ]
    assert services["ApiService"]["Properties"]["ServiceRegistries"] == [
        {"RegistryArn": {"Fn::GetAtt": ["ApiDiscoveryService", "Arn"]}}
    ]
    assert resources["WebAclAssociation"]["Type"] == "AWS::WAFv2::WebACLAssociation"
    runtime_text = (ECS / "scholens-production.yml").read_text(encoding="utf-8")
    assert "/internal/v1" not in runtime_text

    for dockerfile in ("server/Dockerfile", "web/Dockerfile", "jobs/Dockerfile"):
        content = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert re.search(r"^USER (?!root$).+", content, re.MULTILINE)
        assert "@sha256:" in content


def test_python_runtime_images_keep_their_hardened_runtime_contract() -> None:
    server = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    jobs = (ROOT / "jobs" / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert re.search(
        r"ARG PYTHON_IMAGE=python:3\.12\.\d+-alpine3\.23@sha256:[0-9a-f]{64}",
        server,
    )
    assert server.count('"sqlite-libs>=3.53.2-r0"') == 2
    assert re.search(
        r"ARG RUNTIME_IMAGE=gcr\.io/distroless/python3-debian12:nonroot"
        r"@sha256:[0-9a-f]{64}",
        jobs,
    )
    assert "COPY --from=python-runtime /usr/local/ /usr/local/" in jobs
    assert "ENTRYPOINT []" in jobs
    assert "USER nonroot:nonroot" in jobs
    assert "Verify hardened Python runtimes" in workflow
    assert "not os.path.exists('/usr/bin/perl')" in workflow
    assert "not os.path.exists('/bin/sh')" in workflow
    assert "not os.path.exists('/usr/local/bin/pip')" in workflow
    assert "LocalOnnxTextEmbedder().embed_query('code world model')" in workflow


def test_jobs_builder_consumes_the_pinned_embedding_model_revision() -> None:
    jobs = (ROOT / "jobs" / "Dockerfile").read_text(encoding="utf-8")
    builder = jobs.split("FROM ${PYTHON_IMAGE} AS builder", maxsplit=1)[1].split(
        "FROM ${RUNTIME_IMAGE} AS runtime", maxsplit=1
    )[0]

    revision_arg = "ARG SCHOLENS_EMBEDDING_MODEL_REVISION\n"
    download_command = "-m scholens_ai.download_embeddings"
    assert revision_arg in builder
    assert builder.index(revision_arg) < builder.index(download_command)


def test_shared_embedding_runtime_stays_on_the_hardened_onnx_version() -> None:
    pyproject = (ROOT / "packages" / "scholens_ai" / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert '"onnxruntime==1.23.0"' in pyproject


def test_read_only_python_tasks_initialize_writable_temporary_storage() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    workloads = {
        "ApiTaskDefinition": ("api", "ApiImage"),
        "MigrationTaskDefinition": ("migration", "ApiImage"),
        "DocumentWorkerTaskDefinition": ("document-worker", "JobsImage"),
        "ResearchWorkerTaskDefinition": ("research-worker", "JobsImage"),
        "MaintenanceWorkerTaskDefinition": ("maintenance-worker", "JobsImage"),
        "SchedulerTaskDefinition": ("scheduler", "JobsImage"),
    }

    for resource_name, (workload_name, image_parameter) in workloads.items():
        properties = resources[resource_name]["Properties"]
        assert properties["Volumes"] == [{"Name": "tmp"}]
        containers = {
            container["Name"]: container
            for container in properties["ContainerDefinitions"]
        }
        workload = containers[workload_name]
        initializer = containers["tmp-init"]

        assert {
            "ContainerName": "tmp-init",
            "Condition": "SUCCESS",
        } in workload["DependsOn"]
        assert initializer == {
            "Name": "tmp-init",
            "Image": {"Ref": image_parameter},
            "Essential": False,
            "User": "0",
            "EntryPoint": ["/usr/local/bin/python", "-c"],
            "Command": ["from pathlib import Path; Path('/tmp').chmod(0o1777)"],
            "ReadonlyRootFilesystem": True,
            "LinuxParameters": {"Capabilities": {"Drop": ["ALL"]}},
            "MountPoints": [
                {
                    "SourceVolume": "tmp",
                    "ContainerPath": "/tmp",
                    "ReadOnly": False,
                }
            ],
        }


def test_workers_use_sqs_without_a_result_backend_or_beat() -> None:
    jobs = (ROOT / "jobs" / "src" / "celery_app.py").read_text(encoding="utf-8")
    runtime = (ECS / "scholens-production.yml").read_text(encoding="utf-8")

    assert "result_backend=None" in jobs
    assert "task_ignore_result=True" in jobs
    assert '"predefined_queues"' in jobs
    for queue in ("document", "research", "maintenance"):
        assert f"--queues={queue}" in runtime
    assert "celery beat" not in runtime
    assert "AWS::Scheduler::Schedule" in runtime


def test_every_job_producer_has_the_same_validated_callback_base() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    expected = "http://scholens-api.production.svc.sanchezcloud:8000"
    for task_definition, container_name in (
        ("ApiTaskDefinition", "api"),
        ("ConversationWorkerTaskDefinition", "conversation-worker"),
        ("DocumentWorkerTaskDefinition", "document-worker"),
        ("ResearchWorkerTaskDefinition", "research-worker"),
        ("MaintenanceWorkerTaskDefinition", "maintenance-worker"),
        ("SchedulerTaskDefinition", "scheduler"),
    ):
        containers = resources[task_definition]["Properties"]["ContainerDefinitions"]
        container = next(item for item in containers if item["Name"] == container_name)
        environment = {item["Name"]: item["Value"] for item in container["Environment"]}
        assert environment["WEBHOOK_BASE_URL"] == expected

    api = resources["ApiTaskDefinition"]["Properties"]["ContainerDefinitions"][0]
    api_environment = {item["Name"]: item["Value"] for item in api["Environment"]}
    assert api_environment["JOB_UNCLAIMED_TIMEOUT_SECONDS"] == "3600"


def test_production_uses_the_unified_migration_cli_and_gunicorn_runtime() -> None:
    template = load_template("scholens-production.yml")
    dockerfile = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    command = template["Resources"]["MigrationTaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]["Command"]

    assert command == ["migrate"]
    assert 'ENTRYPOINT ["python", "-m", "app.bootstrap.runtime_entrypoint"]' in (
        dockerfile
    )
    entrypoint = (ROOT / "server/app/bootstrap/runtime_entrypoint.py").read_text(
        encoding="utf-8"
    )
    assert '["scholens", "db", "upgrade", "--yes", "--json"]' in entrypoint
    assert '["gunicorn", "-c", "gunicorn.config.py", "app.main:app"]' in entrypoint
    assert "_assert_shared_avatar_runtime_privileges(database_url)" in entrypoint
    assert entrypoint.index(
        "_assert_shared_avatar_runtime_privileges(database_url)"
    ) < (entrypoint.index('"SCHOLENS_MIGRATION_PROOF="'))


def test_api_scaling_respects_the_shared_rds_connection_budget() -> None:
    template = load_template("scholens-production.yml")
    parameters = template["Parameters"]
    resources = template["Resources"]
    container = resources["ApiTaskDefinition"]["Properties"]["ContainerDefinitions"][0]
    environment = {item["Name"]: item["Value"] for item in container["Environment"]}

    api_tasks = parameters["ApiMaxCapacity"]["MaxValue"]
    workers = int(environment["WEB_CONCURRENCY"])
    product_pool = int(environment["DATABASE_POOL_SIZE"]) + int(
        environment["DATABASE_MAX_OVERFLOW"]
    )
    identity_pool = int(environment["AUTH_PG_POOL_MAX_SIZE"])
    scholens_budget = 36

    assert api_tasks * workers * (product_pool + identity_pool) == 30
    assert api_tasks * workers * (product_pool + identity_pool) < scholens_budget
    assert environment["TRUST_CLOUDFLARE_CLIENT_IP"] == "true"
    assert "FORWARDED_ALLOW_IPS" not in environment

    alarm = resources["DatabaseConnectionsAlarm"]["Properties"]
    assert alarm["MetricName"] == "DatabaseConnections"
    assert alarm["Dimensions"] == [
        {"Name": "DBInstanceIdentifier", "Value": "sanchezcloud-pg"}
    ]
    assert parameters["RdsConnectionAlarmThreshold"]["Default"] == 75


def test_production_ai_limits_match_worker_aligned_runtime_defaults() -> None:
    template = load_template("scholens-production.yml")
    container = template["Resources"]["ApiTaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]
    environment = {item["Name"]: item["Value"] for item in container["Environment"]}

    expected = {
        "AI_MAX_INTERACTIVE_PER_USER": "12",
        "AI_MAX_BACKGROUND_PER_USER": "8",
        "AI_MAX_AUDIO_PER_USER": "4",
        "AI_RATE_PER_USER": "120",
        "AI_CONCURRENCY_TTL_SECONDS": "3600",
    }
    assert {name: environment[name] for name in expected} == expected


def test_api_mail_secret_contract_contains_only_aliyun_credentials() -> None:
    template = load_template("scholens-production.yml")
    container = template["Resources"]["ApiTaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]

    mail_secrets: dict[str, str] = {}
    for item in container["Secrets"]:
        substitution, variables = item["ValueFrom"]["Fn::Sub"]
        if variables["Secret"].get("Fn::ImportValue") != (
            "sanchezcloud-scholens-mail-secret-arn"
        ):
            continue
        mail_secrets[item["Name"]] = substitution

    assert mail_secrets == {
        "SCHOLENS_ALIYUN_DM_ACCESS_KEY_ID": "${Secret}:aliyun_access_key_id::",
        "SCHOLENS_ALIYUN_DM_ACCESS_KEY_SECRET": (
            "${Secret}:aliyun_access_key_secret::"
        ),
        "SCHOLENS_ALIYUN_DM_ACCOUNT_NAME": "${Secret}:aliyun_account_name::",
    }

    environment = {item["Name"]: item["Value"] for item in container["Environment"]}
    assert environment["SCHOLENS_ALIYUN_DM_FROM_ALIAS"] == "Scholens"
    assert environment["SCHOLENS_ALIYUN_DM_REPLY_TO_ADDRESS"] == "true"


def test_python_images_copy_shared_packages_before_locked_sync() -> None:
    for dockerfile_path in (
        ROOT / "server" / "Dockerfile",
        ROOT / "jobs" / "Dockerfile",
    ):
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        sync_index = dockerfile.index("RUN uv sync --frozen")
        for shared_package in ("scholens_observability", "scholens_ai"):
            copy_instruction = (
                f"COPY packages/{shared_package}/ /packages/{shared_package}/"
            )
            assert dockerfile.index(copy_instruction) < sync_index


def test_reflow_block_migration_includes_inherited_timestamps() -> None:
    migration = (
        ROOT
        / "server"
        / "migrations"
        / "versions"
        / "2026_07_28_1030_scholens_initial.py"
    ).read_text(encoding="utf-8")
    reflow_blocks = migration.split(
        'op.create_table(\n        "document_reflow_blocks",', 1
    )[1].split("op.create_index(", 1)[0]

    assert '"created_at"' in reflow_blocks
    assert '"updated_at"' in reflow_blocks


def test_entitlement_downgrade_keeps_append_only_cli_origin_vocabulary() -> None:
    migration = (
        ROOT
        / "server"
        / "migrations"
        / "versions"
        / "2026_08_16_1200_entitlement_grants_and_cli_origin.py"
    ).read_text(encoding="utf-8")
    downgrade = migration.split("def downgrade() -> None:", 1)[1]

    assert "one-way vocabulary extension" in downgrade
    assert "ck_operation_journal_origin" not in downgrade


def test_runtime_passage_backfill_never_requires_trigger_ddl() -> None:
    adapter = (
        ROOT
        / "server"
        / "app"
        / "modules"
        / "papers"
        / "infrastructure"
        / "passage_maintenance.py"
    ).read_text(encoding="utf-8")

    assert "ALTER TABLE" not in adapter
    assert "DISABLE TRIGGER" not in adapter
    assert "sanitize_for_postgres" in adapter
    assert "LIMIT :limit" in adapter


def test_database_contract_shares_auth_and_isolates_scholens() -> None:
    bootstrap = (ECS / "database-bootstrap.sql").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "CREATE SCHEMA auth AUTHORIZATION" in bootstrap
    assert "CREATE SCHEMA scholens AUTHORIZATION" in bootstrap
    assert "to_regnamespace('auth') IS NULL" in bootstrap
    assert "to_regnamespace('scholens') IS NULL" in bootstrap
    assert "pg_get_userbyid(nspowner) <> :'auth_migrator_role'" in bootstrap
    assert "pg_get_userbyid(nspowner) <> :'product_migrator_role'" in bootstrap
    assert bootstrap.count("CROSS JOIN LATERAL aclexplode") == 2
    assert "REVOKE ALL ON TABLES FROM %I" in bootstrap
    assert "REVOKE ALL ON SEQUENCES FROM %I" in bootstrap
    assert "GRANT CREATE ON DATABASE" not in bootstrap
    assert "auth_migrator_role" in bootstrap
    assert "product_migrator_role" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE auth.users" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE auth.users" not in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE auth.user_clients" in bootstrap
    assert "GRANT SELECT, INSERT ON TABLE auth.security_events" in bootstrap
    assert "GRANT SELECT ON TABLE auth.user_avatars" in bootstrap
    assert "GRANT INSERT, UPDATE, DELETE ON TABLE auth.user_avatars" not in bootstrap
    assert "REVOKE INSERT, UPDATE, DELETE ON TABLE auth.user_avatars" in bootstrap
    assert "security_events_id_seq" in bootstrap
    assert 'FOR ROLE :"auth_migrator_role"' not in bootstrap
    assert (
        'REVOKE CREATE ON SCHEMA auth FROM :"app_role", :"product_migrator_role"'
        in bootstrap
    )
    assert (
        "REVOKE UPDATE, DELETE ON TABLE scholens.operation_journal_entries" in bootstrap
    )
    assert ci.count("'scholens.operation_journal_entries'") >= 3
    assert "'UPDATE'" in ci
    assert "'DELETE'" in ci
    assert "ALTER DEFAULT PRIVILEGES" in bootstrap
    for current_table in (
        "scholens.documents",
        "scholens.library_papers",
        "scholens.projects",
        "scholens.project_collaborators",
        "scholens.project_papers",
    ):
        assert current_table in ci
    for removed_table in (
        "scholens.papers",
        "scholens.project",
        "scholens.project_role",
        "scholens.project_paper",
    ):
        assert not re.search(rf"{re.escape(removed_table)}(?![a-z_])", ci)


def test_identity_revision_is_consistent_across_runtime_and_ci() -> None:
    lock = (ROOT / "server" / "uv.lock").read_text(encoding="utf-8")
    dockerfile = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    match = re.search(
        r"sanchezcloud-identity\.git\?(?:rev|tag)=[^#\"\s]+#([0-9a-f]{40})", lock
    )
    assert match is not None
    revision = match.group(1)
    assert "ARG SANCHEZCLOUD_IDENTITY_REVISION\n" in dockerfile
    assert "scripts/release_manifest.py identity-revision" in ci
    assert "SANCHEZCLOUD_IDENTITY_REVISION=${{" in ci
    assert "server/.venv/bin/sanchezcloud-identity migrate" in ci
    assert ".ci/sanchezcloud-identity" not in ci
    assert f"ref: {revision}" not in ci


def test_workflows_use_the_scoped_dependency_reader_app() -> None:
    workflows = "\n".join(
        (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for name in ("ci.yml", "publish.yml")
    )

    assert "actions/create-github-app-token@" in workflows
    assert "vars.IDENTITY_READER_APP_ID" in workflows
    assert "secrets.IDENTITY_READER_PRIVATE_KEY" in workflows
    assert "permission-contents: read" in workflows
    assert "CLOUD_AUTH_READ_TOKEN" not in workflows
    assert "origin/master" not in workflows
    assert "default: master" not in workflows


def test_release_workflows_separate_publish_migrate_and_deploy() -> None:
    workflows = {
        name: (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for name in ("publish.yml", "database-production.yml", "release.yml")
    }

    assert "workflow_run:" in workflows["publish.yml"]
    assert "release_manifest.py create" in workflows["publish.yml"]
    assert "scholens-web@$WEB_DIGEST" in workflows["publish.yml"]
    assert "scholens-api@$API_DIGEST" in workflows["publish.yml"]
    assert "scholens-jobs@$JOBS_DIGEST" in workflows["publish.yml"]
    assert "environment: database-production" in workflows["database-production.yml"]
    assert "aws ecs run-task" in workflows["database-production.yml"]
    assert "environment: production" in workflows["release.yml"]
    assert "if ! aws cloudformation deploy" in workflows["release.yml"]
    assert "StackEvents[?ResourceStatusReason!=`null`]" in workflows["release.yml"]
    assert "--s3-bucket" in workflows["release.yml"]
    assert "sanchezcloud-scholens-configuration-key-arn" in workflows["release.yml"]
    assert '--kms-key-id "$template_kms_key_arn"' in workflows["release.yml"]
    assert "create-migration-attestation" in workflows["database-production.yml"]
    assert "verify-migration-transition" in workflows["database-production.yml"]
    assert "migrations/current.json" in workflows["database-production.yml"]
    assert "--if-none-match '*'" in workflows["database-production.yml"]
    assert "verify-database-contract" in workflows["release.yml"]
    assert "migrations/current.json" in workflows["release.yml"]
    assert "Capture previous immutable deployment" in workflows["release.yml"]
    assert (
        "Restore safe release after candidate verification failure"
        in workflows["release.yml"]
    )
    assert "recovery_enabled=false" in workflows["release.yml"]
    assert "recovery_scheduler=DISABLED" in workflows["release.yml"]
    assert "push-by-digest=true" in workflows["publish.yml"]
    assert "ecr_scan_contract.py" in workflows["publish.yml"]
    assert "verify-image-scans" in workflows["publish.yml"]
    assert "imagetools create" in workflows["publish.yml"]
    assert "ecr_scan_contract.py" in workflows["release.yml"]
    assert "verify-image-scans" in workflows["release.yml"]
    combined = "\n".join(workflows.values())
    assert "deploy/production" not in combined
    assert "aws ssm send-command" not in combined


def test_release_uses_current_control_plane_for_candidate_and_rollback_data() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "Check out trusted release control plane" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert 'test "$GITHUB_REF" = refs/heads/main' in workflow
    assert "path: release-source" in workflow
    assert "git -C release-source merge-base --is-ancestor" in workflow
    assert "rollback-source/scripts/release_manifest.py" not in workflow
    assert workflow.count("python scripts/release_manifest.py verify") >= 4
    assert "--source-root release-source" in workflow
    assert "--source-root rollback-source" in workflow
    assert "template-parameters --template" in workflow
    assert workflow.count('--parameter-overrides "${parameter_overrides[@]}"') == 2
    assert '--template-file "$template"' in workflow
    assert "recovery_template=release-source/deploy/ecs/scholens-production.yml" in (
        workflow
    )


def test_release_rejects_an_incomplete_first_runtime_stack() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    readme = (ECS / "README.md").read_text(encoding="utf-8")

    assert "Stacks[0].{Parameters:Parameters,StackStatus:StackStatus}" in workflow
    for status in (
        "CREATE_IN_PROGRESS",
        "CREATE_FAILED",
        "ROLLBACK_IN_PROGRESS",
        "ROLLBACK_FAILED",
        "ROLLBACK_COMPLETE",
        "REVIEW_IN_PROGRESS",
    ):
        assert status in workflow
    assert "delete this never-enabled failed runtime stack" in workflow
    assert "The GitHub role cannot delete stacks" in workflow
    assert "aws cloudformation delete-stack" not in workflow
    assert "another incomplete-create status" in readme
    assert "no `DeleteStack` permission" in readme


def test_release_stages_compatible_runtime_and_recovers_candidate_failures() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    deploy = workflow.index("- name: Deploy digest-qualified ECS release")
    stabilize = workflow.index("Wait for services to stabilize")
    smoke = workflow.index("Verify public deployment")
    recover = workflow.index(
        "Restore safe release after candidate verification failure"
    )
    assert deploy < stabilize < smoke < recover
    smoke_block = workflow[smoke:recover]
    assert "--connect-timeout 5" in smoke_block
    assert "--max-time 20" in smoke_block
    deploy_block = workflow[deploy:stabilize]
    assert re.search(
        r"- name: Deploy digest-qualified ECS release in compatibility order\n"
        r"\s+id: candidate\n"
        r"\s+continue-on-error: true",
        deploy_block,
    )
    for image_output in ("web_image", "api_image", "jobs_image"):
        assert f'echo "{image_output}=$(parameter ' in workflow
    assert 'echo "phase=preflight"' in deploy_block
    assert 'echo "phase=compatibility"' in deploy_block
    assert 'echo "phase=final"' in deploy_block
    assert 'if [[ "$OPERATION" == deploy ]]' in deploy_block
    assert "compatibility_web_image=$PREVIOUS_WEB_IMAGE" in deploy_block
    assert "compatibility_api_image=$candidate_api_image" in deploy_block
    assert "compatibility_jobs_image=$candidate_jobs_image" in deploy_block
    assert "compatibility_web_image=$candidate_web_image" in deploy_block
    assert "compatibility_api_image=$PREVIOUS_API_IMAGE" in deploy_block
    assert "compatibility_jobs_image=$PREVIOUS_JOBS_IMAGE" in deploy_block
    compatibility = deploy_block.index('echo "phase=compatibility"')
    compatibility_smoke = deploy_block.rindex("verify_public_runtime")
    final = deploy_block.index('echo "phase=final"')
    assert compatibility < compatibility_smoke < final
    assert re.search(
        r"- name: Wait for services to stabilize\n"
        r"\s+id: stabilize\n"
        r"\s+continue-on-error: true\n"
        r"\s+if: steps\.candidate\.outcome == 'success'",
        workflow,
    )
    assert workflow.count("steps.candidate.outcome == 'failure' ||") == 2
    assert workflow.count("steps.stabilize.outcome == 'failure' ||") == 2
    assert workflow.count("steps.smoke.outcome == 'failure'") == 2
    assert "steps.candidate.outcome == 'success' &&" in workflow
    assert "steps.stabilize.outcome == 'success' &&" in workflow
    recovery_block = workflow[recover:]
    assert '"$FAILED_PHASE" == final' in recovery_block
    assert "recovery_mode=compatible-backend" in recovery_block
    compatible_start = recovery_block.index('if [[ "$recovered_previous" == true')
    compatible_end = recovery_block.index("recovery_mode=compatible-backend")
    compatible_recovery = recovery_block[compatible_start:compatible_end]
    assert "recovery_scheduler=$PREVIOUS_SCHEDULER_STATE" in compatible_recovery
    assert "recovery_scheduler=$SCHEDULER_STATE" not in compatible_recovery
    assert "recovery_template=deploy/ecs/scholens-production.yml" in recovery_block
    assert "web_image=$PREVIOUS_WEB_IMAGE" in recovery_block
    assert "api_image=$PREVIOUS_API_IMAGE" in recovery_block
    assert "jobs_image=$PREVIOUS_JOBS_IMAGE" in recovery_block
    assert "api_image=$(jq -er .images.api release-manifest.json)" in recovery_block
    assert "jobs_image=$(jq -er .images.jobs release-manifest.json)" in recovery_block
    assert "candidate-verification-recovery" in workflow
    assert "Automatic candidate verification recovery" in workflow
    assert workflow.count("sanchezcloud-scholens-configuration-key-arn") == 2
    assert workflow.count('--kms-key-id "$template_kms_key_arn"') == 2


def test_publish_is_retry_safe_at_every_immutable_commit_boundary() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    recover = workflow.index("Recover an existing immutable manifest")
    build = workflow.index("Build Web and export source maps from one build graph")
    store = workflow.index("Store immutable release assets")
    promote = workflow.index("Verify immutable assets and promote final SHA tags")
    assert recover < build < store < promote
    assert workflow.count("if: steps.existing.outputs.exists == 'false'") >= 8
    assert "push-by-digest=true" in workflow
    assert "git-${RELEASE_SHA}" in workflow
    assert "if existing_digest=$(aws ecr describe-images" in workflow
    assert 'test "$existing_digest" = "$digest"' in workflow
    assert "docker buildx imagetools create" in workflow


def test_web_image_and_source_maps_share_one_buildkit_graph() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    dockerfile = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
    bake = (ROOT / "web" / "docker-bake.hcl").read_text(encoding="utf-8")

    assert workflow.count("docker buildx bake") == 1
    assert "Build Web and export source maps from one build graph" in workflow
    assert 'targets = ["web-runtime", "web-source-maps"]' in bake
    assert bake.count('context    = "./web"') == 2
    assert bake.count("RELEASE_SHA                   = RELEASE_SHA") == 2
    build_stage = dockerfile.split("FROM dependencies AS build", maxsplit=1)[1].split(
        "FROM ${NODE_IMAGE} AS runtime", maxsplit=1
    )[0]
    assert "pnpm build" in build_stage
    assert "node scripts/package-source-maps.mjs" in build_stage
    assert "COPY --from=build" in dockerfile.split("AS runtime", maxsplit=1)[1]
    assert "COPY --from=build /tmp/scholens-source-maps/ /" in dockerfile
    dockerignore = (ROOT / "web" / ".dockerignore").read_text(encoding="utf-8")
    for generated_path in (
        "node_modules",
        ".next",
        "storybook-static",
        "coverage",
        "playwright-report",
        "test-results",
    ):
        assert generated_path in dockerignore.splitlines()


def test_api_task_can_diagnose_only_the_predefined_sqs_queues() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    statements = _policy_statements(resources["ApiTaskRole"])
    queues = next(
        item
        for item in statements
        if {"sqs:GetQueueAttributes", "sqs:SendMessage"} <= _actions(item)
    )

    assert queues["Resource"] == [
        {"Fn::ImportValue": "sanchezcloud-scholens-conversation-queue-arn"},
        {"Fn::ImportValue": "sanchezcloud-scholens-document-queue-arn"},
        {"Fn::ImportValue": "sanchezcloud-scholens-research-queue-arn"},
        {"Fn::ImportValue": "sanchezcloud-scholens-maintenance-queue-arn"},
    ]


def test_release_objects_are_conditionally_created_and_byte_compared() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert "aws s3 cp --recursive" not in workflow
    assert "--if-none-match '*'" in workflow
    assert workflow.count("cmp --silent") >= 2
    assert "prefix=$(jq -er .source_maps.prefix release-manifest.json)" in workflow
    assert (
        "index_key=$(jq -er .source_maps.index_key release-manifest.json)" in workflow
    )
    assert "--source-maps-index web-source-maps/index.json" in workflow
    assert "--image-scan-attestation image-scans.json" in workflow


def test_database_workflow_has_bounded_polling_and_failure_diagnostics() -> None:
    workflow = (ROOT / ".github" / "workflows" / "database-production.yml").read_text(
        encoding="utf-8"
    )

    assert "aws ecs wait tasks-stopped" not in workflow
    assert "deadline=$((SECONDS + 3600))" in workflow
    assert "migration-workflow-timeout" in workflow
    assert "RELEASE_SHA: ${{ inputs.release_sha }}" in workflow
    assert '--arg release_sha "$RELEASE_SHA"' in workflow
    assert '--overrides "$overrides"' in workflow
    assert "stoppedReason:stoppedReason" in workflow
    assert "reason:reason" in workflow
    assert "logStreamName:logStreamName" in workflow
    assert 'expected_log_stream="migration/migration/${task_id}"' in workflow
    assert 'test "$log_stream" = "$expected_log_stream"' in workflow
    assert "sanchezcloud-scholens-application-sg-id" in workflow
    assert "TaskSecurityGroupId" not in workflow
    assert "migration-candidate-task-definition" in workflow
    assert ".containerDefinitions[0].image" not in workflow


def test_foundation_bootstrap_contract_uses_scholight_exports_and_stack_tags() -> None:
    readme = (ECS / "README.md").read_text(encoding="utf-8")
    bootstrap = (ECS / "scholens-foundation-bootstrap.yml").read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "infrastructure-production.yml"
    ).read_text(encoding="utf-8")

    for contract in (
        "sanchezcloud-scholight-mcp-delegation-secret-arn",
        "sanchezcloud-scholight-configuration-key-arn",
        "ScholightMcpDelegationSecretArn",
        "ScholightMcpDelegationKmsKeyArn",
    ):
        assert contract in readme
    for contract in (
        "ScholightMcpDelegationSecretArn",
        "ScholightMcpDelegationKmsKeyArn",
        "sanchezcloud-scholens-scholight-mcp-delegation-secret-arn",
    ):
        assert contract in bootstrap
    for tag in (
        "System=SanchezCloud",
        "Product=Scholens",
        "Environment=production",
        "ManagedBy=CloudFormation",
    ):
        assert tag in readme
        assert tag in workflow
    assert "scholens-foundation-bootstrap.yml" in readme
    assert "AWS_FOUNDATION_CLOUDFORMATION_ROLE_ARN" in readme
    assert "AWS_FOUNDATION_CLOUDFORMATION_ROLE_ARN" in workflow
    assert '--role-arn "$FOUNDATION_CLOUDFORMATION_ROLE_ARN"' in workflow
    assert "AWS_CLOUDFORMATION_ROLE_ARN" not in workflow


def test_foundation_plan_fails_closed_except_for_aws_no_changes() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "infrastructure-production.yml"
    ).read_text(encoding="utf-8")
    wait_block = workflow.split("wait change-set-create-complete", 1)[1].split(
        "describe-change-set", 1
    )[0]

    assert "trap cleanup_change_set EXIT" in workflow
    assert "|| true" not in wait_block
    assert '"$status" == "FAILED"' in workflow
    assert "didn't contain changes" in workflow
    assert 'test "$status" = "CREATE_COMPLETE"' in workflow


def test_candidate_identity_compatibility_workflow_is_standardized() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "sanchezcloud-identity-compat.yml"
    ).read_text(encoding="utf-8")

    for input_name in (
        "identity_ref",
        "version",
        "schema_version",
        "correlation_id",
    ):
        assert f"{input_name}:" in workflow
    assert "actions/create-github-app-token@" in workflow
    assert "permission-contents: read" in workflow
    assert "secrets.IDENTITY_READER_PRIVATE_KEY" in workflow
    assert "uv pip install" in workflow
    assert "AUTH_SCHEMA_VERSION" in workflow
    assert "sanchezcloud-identity migrate" in workflow
    assert "audit-database-role --profile product-runtime" in workflow
    assert "REVOKE SELECT ON auth.user_avatars FROM scholens_app" in workflow
    assert workflow.count("-f deploy/ecs/database-bootstrap.sql") == 3
    assert (
        "has_table_privilege('scholens_app', 'auth.user_avatars', 'SELECT')" in workflow
    )
    assert (
        "has_table_privilege('scholens_app', 'auth.user_avatars', "
        "'INSERT,UPDATE,DELETE')" in workflow
    )
    assert "app_role=scholens_app" in workflow
    assert "SANCHEZCLOUD_IDENTITY_REVISION" in workflow
    assert "CLOUD_AUTH_READ_TOKEN" not in workflow


def test_environment_catalog_matches_shared_identity_conventions() -> None:
    catalog = (ROOT / ".env.example").read_text(encoding="utf-8")
    runtime = (ECS / "scholens-production.yml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for variable in (
        "DATABASE_URL",
        "AUTH_DATABASE_URL",
        "AUTH_JWT_SECRET",
        "AUTH_ACCOUNT_LOCKOUT_THRESHOLD",
        "AUTH_ACCOUNT_LOCKOUT_DURATION_MINUTES",
        "SCHOLENS_ALIYUN_DM_ACCESS_KEY_ID",
        "SCHOLENS_ALIYUN_DM_ACCESS_KEY_SECRET",
        "SCHOLENS_ALIYUN_DM_ACCOUNT_NAME",
        "SCHOLENS_ALIYUN_DM_FROM_ALIAS",
        "SCHOLENS_ALIYUN_DM_REPLY_TO_ADDRESS",
        "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY",
        "SCHOLIGHT_MCP_URL",
        "SCHOLIGHT_MCP_DELEGATION_JWT_SECRET",
        "SCHOLENS_AI_DEEPSEEK_API_KEY",
        "SCHOLENS_AI_STANDARD_MODEL",
        "SCHOLENS_AI_TRANSLATION_MODEL",
        "MOSS_API_KEY",
        "MOSS_MAX_AUDIO_BYTES",
        "JOBS_WEBHOOK_SIGNING_SECRET",
        "PAPER_SEARCH_CURSOR_SECRET",
        "PROJECT_INVITATION_TOKEN_SECRET",
        "NEXT_PUBLIC_API_URL",
    ):
        assert f"{variable}=" in catalog

    assert not (ROOT / "server" / ".env.example").exists()
    for variable in (
        "AUTH_ACCOUNT_LOCKOUT_THRESHOLD",
        "SCHOLENS_ALIYUN_DM_REPLY_TO_ADDRESS",
        "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY",
        "SCHOLIGHT_MCP_DELEGATION_JWT_SECRET",
        "SCHOLENS_AI_DEEPSEEK_API_KEY",
        "MOSS_API_KEY",
        "MOSS_MAX_AUDIO_BYTES",
        "JOBS_WEBHOOK_SIGNING_SECRET",
        "PAPER_SEARCH_CURSOR_SECRET",
        "PROJECT_INVITATION_TOKEN_SECRET",
    ):
        assert f"Name: {variable}" in runtime
    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL" not in runtime
    assert "CELERY_RESULT_BACKEND" not in runtime
    assert "PDF_PARSE_REDIS_URL" not in runtime
    for legacy_variable in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "SCHOLENS_AI_OPENAI_API_KEY",
        "OPENALEX_API_KEY",
        "DEEPSEEK_API_KEY",
        "SCHOLENS_DEEPSEEK_API_KEY",
        "SCHOLIGHT_ACCESS_KEY",
        "JOBS_INTERNAL_SECRET",
        "AUTH_PUBLIC_WEB_URL",
        "AUTH_ALIYUN_DM_ACCESS_KEY_ID",
        "AUTH_ALIYUN_DM_ACCESS_KEY_SECRET",
        "AUTH_ALIYUN_DM_ACCOUNT_NAME",
        "AUTH_ALIYUN_DM_FROM_ALIAS",
        "AUTH_ALIYUN_DM_REPLY_TO_ADDRESS",
        "RESEND_API_KEY",
        "RESEND_FROM_ADDRESS",
        "RESEND_REPLY_TO_ADDRESS",
        "PROFILE_NOTIFICATION_EMAIL",
        "SOURCE_REPOSITORY_URL",
    ):
        assert (
            re.search(
                rf"(?m)^\s*{re.escape(legacy_variable)}\s*[=:]",
                catalog + runtime + ci,
            )
            is None
        )
    assert "EXA_API_KEY" not in catalog + runtime
    assert "FIRECRAWL_API_KEY" not in catalog + runtime


def test_account_center_url_is_a_web_build_value_not_runtime_configuration() -> None:
    readme = (ECS / "README.md").read_text(encoding="utf-8")
    runtime = (ECS / "scholens-production.yml").read_text(encoding="utf-8")
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL" in readme
    assert "Web build-time" in readme
    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL" not in runtime
    assert "ACCOUNT_CENTER_URL: ${{ vars.ACCOUNT_CENTER_URL }}" in publish
    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL" in (
        ROOT / "web" / "docker-bake.hcl"
    ).read_text(encoding="utf-8")


def test_local_development_uses_the_scholens_migrator_name() -> None:
    development = (ROOT / "DEVELOPMENT.md").read_text(encoding="utf-8")

    assert "scholens_migrator" in development


def test_environment_catalog_covers_code_references() -> None:
    assignment = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
    catalog_variables = set(
        assignment.findall((ROOT / ".env.example").read_text(encoding="utf-8"))
    )

    code_patterns = (
        re.compile(r'(?:os\.getenv|os\.environ\.get)\(\s*["\']([A-Z][A-Z0-9_]*)'),
        re.compile(r'os\.environ\[\s*["\']([A-Z][A-Z0-9_]*)'),
        re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
    )
    code_variables: set[str] = set()
    for source_root in (
        ROOT / "server" / "app",
        ROOT / "jobs" / "src",
        ROOT / "web" / "src",
        ROOT / "client" / "src",
    ):
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in {
                ".py",
                ".js",
                ".mjs",
                ".ts",
                ".tsx",
            }:
                continue
            source = path.read_text(encoding="utf-8")
            for pattern in code_patterns:
                code_variables.update(pattern.findall(source))

    platform_injected_variables = {
        "AWS_DEFAULT_REGION",
        "AWS_EXECUTION_ENV",
        "AWS_LAMBDA_FUNCTION_NAME",
        "ECS_AGENT_URI",
        "NODE_ENV",
    }
    dormant_first_release_variables = {
        "NEXT_PUBLIC_POSTHOG_HOST",
        "NEXT_PUBLIC_POSTHOG_KEY",
        "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY",
        "POSTHOG_API_KEY",
        "STRIPE_API_KEY",
        "STRIPE_MONTHLY_PRICE_ID",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_YEARLY_PRICE_ID",
    }
    assert dormant_first_release_variables.isdisjoint(catalog_variables)
    assert (
        code_variables - platform_injected_variables - dormant_first_release_variables
        <= catalog_variables
    )


def test_migration_chain_starts_with_the_consolidated_baseline() -> None:
    versions = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))

    assert [path.name for path in versions] == [
        "2026_07_28_1030_scholens_initial.py",
        "2026_08_16_1200_entitlement_grants_and_cli_origin.py",
        "2026_08_18_1200_project_upload_library_expand.py",
        "2026_08_20_1200_conversation_failure_metadata.py",
        "2026_08_20_1200_hybrid_paper_search_expand.py",
        "2026_08_20_1230_search_embedding_timestamps_expand.py",
        "2026_08_21_1200_paper_list_preferences.py",
        "2026_08_21_1630_conversation_search_indexes.py",
        "2026_08_22_1015_paper_list_layout_sizes.py",
        "2026_08_24_1700_reading_activity_ledger.py",
    ]
    baseline = versions[0].read_text(encoding="utf-8")
    assert "down_revision: str | None = None" in baseline
    assert "scholens.document_content_trigger" in baseline
    assert "scholens.document_passages_tsvector_trigger" in baseline
    assert "ON scholens.documents" in baseline
    assert "ON scholens.document_passages" in baseline
    assert "conversation_context_projects" in baseline
    assert "conversation_context_documents" in baseline
    assert '"tool_invocations"' in baseline
    assert '"access_keys"' in baseline
    for field in ("title", "authors", "keywords", "abstract", "raw_content"):
        assert f"NEW.{field}" in baseline
    assert "paper_passages" not in baseline
    assert "discover_searches" not in baseline
    assert '"integration_connections"' in baseline
    assert "'mineru'" in baseline


def test_global_discovery_surfaces_are_absent_from_client_sources() -> None:
    protected_routes = ROOT / "client" / "src" / "app" / "(main)" / "(protected)"
    assert not (protected_routes / "discover").exists()
    assert not (protected_routes / "finder").exists()

    product_surfaces = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "README.md",
            ROOT / "client" / "src" / "app" / "sitemap.ts",
            ROOT / "client" / "src" / "components" / "QuickActions.tsx",
            ROOT / "client" / "src" / "components" / "sidebar" / "navItems.ts",
            ROOT
            / "server"
            / "app"
            / "modules"
            / "projects"
            / "infrastructure"
            / "invitation_email.py",
        )
    )
    for removed_identifier in (
        "/discover",
        "/finder",
        "Discover Research",
        "Document Finder",
    ):
        assert removed_identifier not in product_surfaces


def test_server_keeps_the_typed_sqlalchemy_two_mainline() -> None:
    app_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "server" / "app").rglob("*.py")
    )
    model_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "server" / "app" / "database" / "models").glob("*.py")
    )
    pyproject = (ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8")

    assert "db.query(" not in app_sources
    assert "type: ignore" not in app_sources
    assert re.search(r"\bColumn\(", model_sources) is None
    assert "sqlalchemy.ext.mypy.plugin" not in pyproject


def test_pdf_viewer_has_one_browser_only_loading_boundary() -> None:
    wrapper = (
        ROOT / "client" / "src" / "components" / "PdfHighlighterViewer.tsx"
    ).read_text(encoding="utf-8")
    implementation = (
        ROOT / "client" / "src" / "components" / "PdfHighlighterViewerClient.tsx"
    ).read_text(encoding="utf-8")
    package = (ROOT / "client" / "package.json").read_text(encoding="utf-8")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert 'import("./PdfHighlighterViewerClient")' in wrapper
    assert "ssr: false" in wrapper
    assert "react-pdf-highlighter-extended" not in wrapper
    assert "react-pdf-highlighter-extended" in implementation
    assert '"predev": "node scripts/sync-pdf-worker.mjs"' in package
    assert '"prebuild": "node scripts/sync-pdf-worker.mjs"' in package
    assert "client/public/pdf.worker.mjs" in ignore


def test_alb_routes_only_reviewed_public_api_prefixes() -> None:
    template = load_template("scholens-production.yml")
    resources = template["Resources"]
    values = {
        value
        for rule in ("ApiListenerRule", "OperatorListenerRule")
        for value in resources[rule]["Properties"]["Conditions"][0][
            "PathPatternConfig"
        ]["Values"]
    }

    assert values == {
        "/api/v1",
        "/api/v1/*",
        "/webhooks/v1",
        "/webhooks/v1/*",
        "/mcp",
        "/mcp/*",
        "/admin",
        "/admin/*",
    }
    assert all("internal" not in value for value in values)
    assert resources["LoadBalancer"]["Properties"]["Scheme"] == "internet-facing"
    assert resources["LoadBalancer"]["Properties"]["IpAddressType"] == "ipv4"
    ingress = resources["LoadBalancerSecurityGroup"]["Properties"][
        "SecurityGroupIngress"
    ]
    assert all("CidrIpv6" not in rule for rule in ingress)
    assert resources["WebAcl"]["Properties"]["Rules"][0]["Name"] == (
        "RequireCloudflareOriginToken"
    )
    assert resources["ApiService"]["DependsOn"] == [
        "ApiListenerRule",
        "OperatorListenerRule",
    ]


def test_waf_large_body_exceptions_are_path_scoped() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    rules = {rule["Name"]: rule for rule in resources["WebAcl"]["Properties"]["Rules"]}
    standard = rules["CommonThreatsStandardBodies"]["Statement"][
        "ManagedRuleGroupStatement"
    ]
    reviewed = rules["CommonThreatsReviewedLargeBodies"]["Statement"][
        "ManagedRuleGroupStatement"
    ]

    assert "ExcludedRules" not in standard
    assert "ExcludedRules" not in reviewed
    assert reviewed["RuleActionOverrides"] == [
        {"Name": "SizeRestrictions_BODY", "ActionToUse": {"Count": {}}},
        {"Name": "EC2MetaDataSSRF_BODY", "ActionToUse": {"Count": {}}},
        {"Name": "GenericLFI_BODY", "ActionToUse": {"Count": {}}},
        {"Name": "GenericRFI_BODY", "ActionToUse": {"Count": {}}},
        {"Name": "CrossSiteScripting_BODY", "ActionToUse": {"Count": {}}},
    ]
    assert resources["LargeBodyPathSet"]["Properties"]["RegularExpressionList"] == [
        "^/mcp$",
        "^/api/v1/conversations(?:/.*)?$",
        "^/api/v1/paper-ingestions(?:/.*)?$",
    ]
    assert resources["ContentFreeTextPathSet"]["Properties"][
        "RegularExpressionList"
    ] == [
        "^/api/v1/papers/[^/]+/selection-translations$",
        "^/api/v1/papers/[^/]+/annotation-threads(?:/.*)?$",
        "^/api/v1/annotation-threads(?:/.*)?$",
        "^/api/v1/annotation-comments(?:/.*)?$",
        "^/api/v1/library/papers/[^/]+$",
        "^/api/v1/me/translation-preferences$",
        "^/api/v1/projects(?:/[^/]+(?:/data-tables)?)?$",
        "^/api/v1/me/onboarding$",
        "^/api/v1/(?:papers|projects)/[^/]+/audio-overviews$",
        "^/api/v1/search/(?:conversations|papers|research)$",
    ]
    assert str(standard["ScopeDownStatement"]).count("LargeBodyPathSet") == 1
    assert str(standard["ScopeDownStatement"]).count("ContentFreeTextPathSet") == 1
    assert str(reviewed["ScopeDownStatement"]).count("LargeBodyPathSet") == 1
    assert str(reviewed["ScopeDownStatement"]).count("ContentFreeTextPathSet") == 1
    assert "'FieldToMatch': {'UriPath': {}}" in str(standard["ScopeDownStatement"])
    assert "'FieldToMatch': {'UriPath': {}}" in str(reviewed["ScopeDownStatement"])


def test_waf_free_text_path_sets_classify_every_public_write_route() -> None:
    """Every public write route with a body must be explicitly classified.

    A route is either matched by one of the two path sets (CRS body rules run
    in Count mode) or listed in the structured whitelist below (full CRS body
    inspection). A new or renamed public write route that lands in neither
    bucket fails this test, which is the classification obligation of the
    change that introduces it.
    """
    resources = load_template("scholens-production.yml")["Resources"]
    exempt_patterns = (
        resources["LargeBodyPathSet"]["Properties"]["RegularExpressionList"]
        + resources["ContentFreeTextPathSet"]["Properties"]["RegularExpressionList"]
    )

    # Paths that must keep full CRS body inspection. Their bodies are
    # structured (enums, UUIDs, patterns, credentials, short labels) and
    # should never need the free-text Count treatment.
    structured_whitelist = {
        "PUT /api/v1/admin/users/{user_id}/block",
        "POST /api/v1/auth/change-password",
        "POST /api/v1/auth/forgot-password",
        "POST /api/v1/auth/login",
        "POST /api/v1/auth/register",
        "POST /api/v1/auth/resend-verification",
        "POST /api/v1/auth/reset-password",
        "POST /api/v1/auth/verify-email",
        "POST /api/v1/integrations/zotero/imports",
        "POST /api/v1/integrations/zotero/oauth/authorizations",
        "PUT /api/v1/integrations/zotero/sync-preferences",
        "POST /api/v1/library/paper-removals",
        "POST /api/v1/library/papers",
        "POST /api/v1/library/tags",
        "PUT /api/v1/library/tags/assignments",
        "PATCH /api/v1/library/tags/{tag_id}",
        "POST /api/v1/me/access-keys",
        "PATCH /api/v1/me/access-keys/{access_key_id}",
        "PATCH /api/v1/me/integrations/{provider}",
        "PUT /api/v1/me/integrations/{provider}",
        "PATCH /api/v1/me/profile",
        "PUT /api/v1/me/profile",
        "PUT /api/v1/me/paper-list-preferences",
        "POST /api/v1/me/reading-activity/paper-summaries",
        "PUT /api/v1/me/reading-activity-preferences",
        "POST /api/v1/papers/{document_id}/reading-sessions",
        "POST /api/v1/projects/{project_id}/invitations",
        "PATCH /api/v1/projects/{project_id}/members/{user_id}",
        "POST /api/v1/projects/{project_id}/papers",
        "POST /api/v1/projects/{project_id}/transfer",
        "PUT /api/v1/reading-sessions/{session_id}",
    }

    openapi = json.loads(
        (ROOT / "server" / "openapi" / "public-v1.json").read_text(encoding="utf-8")
    )
    body_paths = []
    for path, methods in openapi["paths"].items():
        for method in ("post", "put", "patch"):
            if method in methods and "requestBody" in methods[method]:
                body_paths.append((method.upper(), path))

    compiled = [re.compile(pattern) for pattern in exempt_patterns]

    def exempt(path: str) -> bool:
        return any(pattern.fullmatch(path) for pattern in compiled)

    # Every body-bearing write route is classified exactly once. Note: the
    # Annotation edits deliberately stay in the free-text scope because thread
    # and comment bodies contain user-authored text. Structured project
    # membership, paper-assignment, and ownership-transfer bodies do not.
    for method, path in body_paths:
        key = f"{method} {path}"
        if exempt(path):
            assert key not in structured_whitelist, (
                f"{key} is both free-text-exempt and in the structured "
                "whitelist; it must be classified exactly once"
            )
        else:
            assert key in structured_whitelist, (
                f"{key} is not classified by the WAF body policy; add it to "
                "the free-text path sets or the structured whitelist"
            )

    # The whitelist stays honest: every entry is a real body-bearing route.
    body_keys = {f"{method} {path}" for method, path in body_paths}
    assert structured_whitelist <= body_keys

    # Every exemption pattern earns its place by matching a real body-bearing
    # route. `^/mcp$` is the documented constant exception: the MCP route is
    # not part of the public OpenAPI snapshot.
    for pattern in exempt_patterns:
        if pattern == "^/mcp$":
            continue
        assert any(re.fullmatch(pattern, path) for _, path in body_paths), (
            f"dead WAF path-set regex: {pattern}"
        )


def test_waf_logging_redacts_origin_and_auth_headers() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
    log_group = resources["WafLogGroup"]
    assert log_group["Properties"]["LogGroupName"].startswith("aws-waf-logs-")
    assert log_group["Properties"]["RetentionInDays"] == 30

    logging = resources["WebAclLoggingConfiguration"]["Properties"]
    assert logging["ResourceArn"] == {"Fn::GetAtt": ["WebAcl", "Arn"]}
    assert logging["LogDestinationConfigs"] == [{"Fn::GetAtt": ["WafLogGroup", "Arn"]}]
    redacted = logging["RedactedFields"]
    assert {"SingleHeader": {"Name": "x-scholens-origin"}} in redacted
    assert {"SingleHeader": {"Name": "cookie"}} in redacted
    assert {"SingleHeader": {"Name": "authorization"}} in redacted
    assert logging["LoggingFilter"] == {
        "DefaultBehavior": "DROP",
        "Filters": [
            {
                "Behavior": "KEEP",
                "Requirement": "MEETS_ANY",
                "Conditions": [
                    {"ActionCondition": {"Action": "BLOCK"}},
                    {"ActionCondition": {"Action": "COUNT"}},
                    {"ActionCondition": {"Action": "EXCLUDED_AS_COUNT"}},
                ],
            }
        ],
    }


def test_waf_logs_substitute_request_bodies() -> None:
    web_acl = load_template("scholens-production.yml")["Resources"]["WebAcl"]

    assert web_acl["Properties"]["DataProtectionConfig"] == {
        "DataProtections": [
            {
                "Field": {"FieldType": "BODY"},
                "Action": "SUBSTITUTION",
                "ExcludeRuleMatchDetails": False,
                "ExcludeRateBasedDetails": False,
            }
        ]
    }


def test_waf_never_samples_requests_that_carry_the_origin_secret() -> None:
    web_acl = load_template("scholens-production.yml")["Resources"]["WebAcl"]

    assert web_acl["Properties"]["VisibilityConfig"]["SampledRequestsEnabled"] is False
    assert all(
        rule["VisibilityConfig"]["SampledRequestsEnabled"] is False
        for rule in web_acl["Properties"]["Rules"]
    )


def test_runbook_locks_production_environment_and_secret_preflights() -> None:
    readme = (ECS / "README.md").read_text(encoding="utf-8")

    for environment in (
        "image-publish",
        "database-production",
        "production",
        "infrastructure-production",
    ):
        assert environment in readme
    assert "only the `main` branch" in readme
    assert "must not allow tags" in readme
    assert "/sanchezcloud/scholens/production/ai`" in readme
    assert "/sanchezcloud/scholens/production/ai-providers" not in readme
    assert "get-secret-value" in readme
    assert "all($required[];" in readme
    for generated in ("cache-api", "cache-jobs", "database", "core", "edge"):
        assert generated in readme
    for operator_managed in ("ai", "mail", "integrations"):
        assert operator_managed in readme
    assert "/sanchezcloud/scholens/production/billing" not in readme

    bootstrap = readme[readme.index("## Initial production bootstrap") :]
    disabled = bootstrap.index("ApplicationEnabled=false")
    migration = bootstrap.index("Run protected product migration")
    cloudflare = bootstrap.index("Point the proxied Cloudflare CNAME")
    enabled = bootstrap.index("ApplicationEnabled=true")
    scheduler = bootstrap.index("Enable the scheduler")
    assert disabled < migration < cloudflare < enabled < scheduler
    assert "immediately requires both public Cloudflare health checks" in bootstrap


def test_operator_managed_secret_containers_have_no_cloudformation_value() -> None:
    resources = load_template("scholens-foundation.yml")["Resources"]

    assert "BillingSecret" not in resources
    for name in ("AiSecret", "MailSecret", "IntegrationsSecret"):
        properties = resources[name]["Properties"]
        assert "SecretString" not in properties
        assert "GenerateSecretString" not in properties


def test_core_secret_seed_shape_stays_frozen() -> None:
    template = load_template("scholens-foundation.yml")
    generated = template["Resources"]["CoreSecret"]["Properties"][
        "GenerateSecretString"
    ]
    seed = json.loads(generated["SecretStringTemplate"])

    assert seed == {
        "admin_session_secret": "",
        "paper_search_cursor_secret": "",
        "jobs_webhook_signing_secret": "",
        "integration_credential_encryption_key": "",
    }
    assert "project_invitation_token_secret" not in seed

    readme = (ECS / "README.md").read_text(encoding="utf-8")
    assert "CoreSecret.GenerateSecretString" in readme
    assert "frozen first-stack seed" in readme
    assert "can replace the operator-owned `AWSCURRENT` value" in readme


def test_edge_rotation_version_lookup_never_reads_the_secret_value() -> None:
    readme = (ECS / "README.md").read_text(encoding="utf-8")
    start = readme.index(
        "The deploy workflow takes the current and previous edge-secret"
    )
    end = readme.index("The cross-product migration order is strict", start)
    rotation = readme[start:end]

    assert rotation.count("aws secretsmanager list-secret-version-ids") == 2
    assert "AWSCURRENT" in rotation
    assert "AWSPREVIOUS" in rotation
    assert "get-secret-value" not in rotation
    assert "EDGE_PREVIOUS_VERSION_ID=$EDGE_CURRENT_VERSION_ID" in rotation
    assert "An absent `AWSPREVIOUS` is normal" in rotation


def test_ci_builds_images_and_runs_independent_migrations_twice() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gate_runner = (ROOT / "scripts" / "run-gates.sh").read_text(encoding="utf-8")

    assert "tags: scholens-api:ci" in workflow
    assert "for _ in 1 2; do" in workflow
    assert "sanchezcloud-identity migrate" in workflow
    assert workflow.count("--entrypoint scholens") == 2
    assert "db upgrade --yes --json" in workflow
    assert "scholens-api:ci verify paper-search" in workflow
    assert "scholens-api:ci scholens verify paper-search" not in workflow
    assert "scholens dev reset-product" in workflow
    assert "RESET-SCHOLENS-LOCAL" in workflow
    assert "account_plan_grants" in workflow
    assert "account_quota_overrides" in workflow
    assert 'alembic upgrade "$base_head"' in workflow
    assert "ci-migration-preservation@example.com" in workflow
    assert "migration_policy_compatibility.py" in workflow
    assert "alembic downgrade" not in workflow
    assert "WHERE origin_kind = 'cli'" in workflow
    assert "test_postgres_quota_invariants.py" in workflow
    assert "--entrypoint alembic" in workflow
    assert "CREATE TABLE auth.product_migrator_must_not_create" in workflow
    assert "CREATE TABLE scholens.auth_migrator_must_not_create" in workflow

    server_dockerfile = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY --from=builder /app/migrations/ /app/migrations/" in server_dockerfile
    assert "SCHOLENS_SERVER_ROOT=/app" in server_dockerfile
    builder = server_dockerfile.split("FROM ${PYTHON_IMAGE} AS builder", maxsplit=1)[
        1
    ].split("FROM ${PYTHON_IMAGE} AS runtime", maxsplit=1)[0]
    assert "ARG RDS_GLOBAL_BUNDLE_URL" in builder
    assert "ARG RDS_GLOBAL_BUNDLE_SHA256" in builder

    for lane in (
        "server",
        "jobs",
        "shared-packages",
        "web",
        "client",
        "deployment",
    ):
        assert f"./scripts/run-gates.sh {lane}" in workflow

    assert '"$environment/mypy" app' in gate_runner
    assert '"$environment/mypy" src' in gate_runner
    assert '"$environment/ruff" format --check app tests migrations' in gate_runner
    assert '"$environment/ruff" format --check src tests' in gate_runner
    assert "window is not defined|document is not defined" in gate_runner


def test_ci_has_one_stable_aggregate_required_check() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "all-checks-passed:" in workflow
    assert "name: all checks passed" in workflow
    assert "public-contract-compatibility:" in workflow
    assert "github.com/oasdiff/oasdiff@v1.29.1" in workflow
    assert workflow.count("oasdiff breaking") == 2
    assert "mcp_contract_compatibility.py check-metadata" in workflow
    assert "mcp_contract_compatibility.py check-schema-corrections" in workflow
    assert "server/contracts/schema-corrections.json" in workflow
    assert "deprecation_registry.py" in workflow
    for dependency in (
        "server",
        "jobs",
        "shared-packages",
        "web",
        "client",
        "deployment-contract",
        "public-contract-compatibility",
    ):
        assert f"      - {dependency}" in workflow


def test_root_gate_runner_has_no_provisioning_or_runtime_side_effects() -> None:
    gate_runner = (ROOT / "scripts" / "run-gates.sh").read_text(encoding="utf-8")

    for forbidden_command in (
        "uv sync",
        "pnpm install",
        "yarn install",
        "alembic upgrade",
        "migrate_product",
        "docker compose up",
        "pnpm dev",
    ):
        assert forbidden_command not in gate_runner


def test_external_actions_are_pinned_to_full_commit_shas() -> None:
    action_reference = re.compile(r"^\s*uses:\s*([^\s]+)@([^\s#]+)", re.MULTILINE)
    for name in (
        "ci.yml",
        "database-production.yml",
        "infrastructure-production.yml",
        "publish.yml",
        "release.yml",
        "sanchezcloud-identity-compat.yml",
    ):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for action, revision in action_reference.findall(workflow):
            if action.startswith("./"):
                continue
            assert re.fullmatch(r"[0-9a-f]{40}", revision), (
                f"{action}@{revision} is mutable"
            )
