"""Static contracts for the production deployment package."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
ECS = ROOT / "deploy" / "ecs"
FOUNDATION_INLINE_LIMIT = 48 * 1024


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
    template = ECS / "scholens-foundation.yml"
    assert len(template.read_bytes()) < FOUNDATION_INLINE_LIMIT


def test_foundation_inline_role_policies_fit_iam_aggregate_quota() -> None:
    resources = load_template("scholens-foundation.yml")["Resources"]
    for name, resource in resources.items():
        if resource["Type"] != "AWS::IAM::Role":
            continue
        policies = resource.get("Properties", {}).get("Policies", [])
        aggregate = sum(
            len(json.dumps(policy["PolicyDocument"], separators=(",", ":")))
            for policy in policies
        )
        assert aggregate <= 10_240, f"{name} inline policies use {aggregate} bytes"


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
            assert resource["DeletionPolicy"] == "Retain"
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

    cache = resources["Cache"]["Properties"]
    assert cache["Engine"] == "valkey"
    assert cache["UserGroupId"] == {"Ref": "CacheUserGroup"}

    release = resources["ReleaseBucket"]["Properties"]
    assert release["ObjectLockEnabled"] is True
    assert release["ObjectLockConfiguration"] == {
        "ObjectLockEnabled": "Enabled",
        "Rule": {"DefaultRetention": {"Mode": "COMPLIANCE", "Days": 365}},
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


def test_foundation_roles_enforce_immutable_release_and_scoped_secrets() -> None:
    resources = load_template("scholens-foundation.yml")["Resources"]
    publish = _policy_statements(resources["PublishRole"])
    production = _policy_statements(resources["ProductionDeployRole"])
    execution = _policy_statements(resources["TaskExecutionRole"])

    assert all("s3:BypassGovernanceRetention" not in _actions(item) for item in publish)
    publish_put = next(item for item in publish if "s3:PutObject" in _actions(item))
    assert publish_put["Resource"] == [
        {"Fn::Sub": "${ReleaseBucket.Arn}/releases/*"},
        {"Fn::Sub": "${ReleaseBucket.Arn}/source-maps/*"},
    ]
    production_put = next(
        item for item in production if "s3:PutObject" in _actions(item)
    )
    assert production_put["Resource"] == {
        "Fn::Sub": "${ReleaseBucket.Arn}/cloudformation/*"
    }
    assert not any(
        "secretsmanager:GetSecretValue" in _actions(item)
        and item["Resource"] == {"Ref": "EdgeSecret"}
        for item in production
    )
    execution_secret = next(
        item for item in execution if "secretsmanager:GetSecretValue" in _actions(item)
    )
    assert {"Ref": "ScholightMcpDelegationSecretArn"} in execution_secret["Resource"]
    assert "sanchezcloud-scholight-core-secret-arn" not in str(execution)


def test_cloudformation_role_has_current_scoped_waf_association_permissions() -> None:
    resources = load_template("scholens-foundation.yml")["Resources"]
    statements = _policy_statements(resources["CloudFormationServiceRole"])
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
            "regional/webacl/sanchezcloud-scholens/*"
        )
    }
    iam_actions = {
        action
        for statement in statements
        for action in _actions(statement)
        if action.startswith("iam:")
    }
    assert "iam:*" not in iam_actions

    iam_statements = [
        item
        for item in statements
        if any(action.startswith("iam:") for action in _actions(item))
    ]
    for item in iam_statements:
        assert item["Resource"] != "*"
        if "iam:CreateServiceLinkedRole" in _actions(item):
            assert "role/aws-service-role/*" in str(item["Resource"])
            assert "iam:AWSServiceName" in str(item["Condition"])
        else:
            assert "role/SanchezCloudScholens" in str(item["Resource"])

    for service in ("ecr:", "secretsmanager:"):
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
    assert not any(
        action.startswith(("iam:", "ecr:", "s3:")) for action in broad_actions
    )
    assert {
        action for action in broad_actions if action.startswith("secretsmanager:")
    } <= {"secretsmanager:GetRandomPassword"}


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
        "DocumentWorkerScalableTarget",
        "ResearchWorkerScalableTarget",
        "MaintenanceWorkerScalableTarget",
    }
    for target in targets.values():
        minimum = target["Properties"]["MinCapacity"]["Fn::If"]
        maximum = target["Properties"]["MaxCapacity"]["Fn::If"]
        assert minimum[0] == maximum[0] == "RunApplication"
        assert minimum[2] == maximum[2] == 0


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


def test_scheduler_and_worker_task_protection_are_cluster_scoped() -> None:
    resources = load_template("scholens-production.yml")["Resources"]
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
        "DocumentWorkerService",
        "ResearchWorkerService",
        "MaintenanceWorkerService",
    ):
        providers = services[name]["Properties"]["CapacityProviderStrategy"]
        assert {entry["CapacityProvider"] for entry in providers} == {
            "FARGATE",
            "FARGATE_SPOT",
        }

    assert resources["ApiDiscoveryService"]["Type"] == "AWS::ServiceDiscovery::Service"
    assert resources["WebAclAssociation"]["Type"] == "AWS::WAFv2::WebACLAssociation"
    runtime_text = (ECS / "scholens-production.yml").read_text(encoding="utf-8")
    assert "/internal/v1" not in runtime_text

    for dockerfile in ("server/Dockerfile", "web/Dockerfile", "jobs/Dockerfile"):
        content = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert re.search(r"^USER (?!root$).+", content, re.MULTILINE)
        assert "@sha256:" in content


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

    assert "CREATE SCHEMA IF NOT EXISTS auth" in bootstrap
    assert "CREATE SCHEMA IF NOT EXISTS scholens" in bootstrap
    assert "GRANT CREATE ON DATABASE" not in bootstrap
    assert "auth_migrator_role" in bootstrap
    assert "product_migrator_role" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE auth.users" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE auth.users" not in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE auth.user_clients" in bootstrap
    assert "GRANT SELECT, INSERT ON TABLE auth.security_events" in bootstrap
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
    assert f"ARG SANCHEZCLOUD_IDENTITY_REVISION={revision}" in dockerfile
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
    assert "aws cloudformation deploy" in workflows["release.yml"]
    assert "--s3-bucket" in workflows["release.yml"]
    combined = "\n".join(workflows.values())
    assert "deploy/production" not in combined
    assert "aws ssm send-command" not in combined


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


def test_release_objects_are_conditionally_created_and_byte_compared() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert "aws s3 cp --recursive" not in workflow
    assert "--if-none-match '*'" in workflow
    assert workflow.count("cmp --silent") >= 2
    assert '"source-maps/${RELEASE_SHA}/index.json"' in workflow
    assert "--source-maps-index web-source-maps/index.json" in workflow


def test_database_workflow_has_bounded_polling_and_failure_diagnostics() -> None:
    workflow = (ROOT / ".github" / "workflows" / "database-production.yml").read_text(
        encoding="utf-8"
    )

    assert "aws ecs wait tasks-stopped" not in workflow
    assert "deadline=$((SECONDS + 3600))" in workflow
    assert "migration-workflow-timeout" in workflow
    assert "stoppedReason:stoppedReason" in workflow
    assert "reason:reason" in workflow
    assert "logStreamName:logStreamName" in workflow


def test_foundation_bootstrap_contract_uses_scholight_exports_and_stack_tags() -> None:
    readme = (ECS / "README.md").read_text(encoding="utf-8")
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
        assert contract in workflow
    for tag in (
        "System=SanchezCloud",
        "Product=Scholens",
        "Environment=production",
        "ManagedBy=CloudFormation",
    ):
        assert tag in readme
        assert tag in workflow


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
        "AUTH_ALIYUN_DM_ACCESS_KEY_ID",
        "AUTH_ALIYUN_DM_ACCESS_KEY_SECRET",
        "AUTH_ALIYUN_DM_ACCOUNT_NAME",
        "AUTH_ALIYUN_DM_FROM_ALIAS",
        "AUTH_ALIYUN_DM_REPLY_TO_ADDRESS",
        "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY",
        "SCHOLIGHT_MCP_URL",
        "SCHOLIGHT_MCP_DELEGATION_JWT_SECRET",
        "SCHOLENS_AI_DEEPSEEK_API_KEY",
        "SCHOLENS_AI_OPENAI_API_KEY",
        "SCHOLENS_AI_STANDARD_MODEL",
        "SCHOLENS_AI_TRANSLATION_MODEL",
        "MOSS_API_KEY",
        "MOSS_MAX_AUDIO_BYTES",
        "JOBS_WEBHOOK_SIGNING_SECRET",
        "PAPER_SEARCH_CURSOR_SECRET",
        "NEXT_PUBLIC_API_URL",
    ):
        assert f"{variable}=" in catalog

    assert not (ROOT / "server" / ".env.example").exists()
    for variable in (
        "AUTH_ACCOUNT_LOCKOUT_THRESHOLD",
        "AUTH_ALIYUN_DM_REPLY_TO_ADDRESS",
        "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY",
        "SCHOLIGHT_MCP_DELEGATION_JWT_SECRET",
        "SCHOLENS_AI_DEEPSEEK_API_KEY",
        "MOSS_API_KEY",
        "MOSS_MAX_AUDIO_BYTES",
        "JOBS_WEBHOOK_SIGNING_SECRET",
        "PAPER_SEARCH_CURSOR_SECRET",
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
        "DEEPSEEK_API_KEY",
        "SCHOLENS_DEEPSEEK_API_KEY",
        "SCHOLIGHT_ACCESS_KEY",
        "JOBS_INTERNAL_SECRET",
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
    assert "openpaper_local" not in development


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
            if path.suffix not in {".py", ".js", ".mjs", ".ts", ".tsx"}:
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
    assert code_variables - platform_injected_variables <= catalog_variables


def test_migration_chain_starts_with_the_consolidated_baseline() -> None:
    versions = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))

    assert [path.name for path in versions] == [
        "2026_07_28_1030_scholens_initial.py",
        "2026_08_16_1200_entitlement_grants_and_cli_origin.py",
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
            ROOT / "client" / "design.md",
            ROOT / "client" / "src" / "app" / "sitemap.ts",
            ROOT / "client" / "src" / "components" / "QuickActions.tsx",
            ROOT / "client" / "src" / "components" / "sidebar" / "navItems.ts",
            ROOT / "client" / "src" / "content" / "introducing.mdx",
            ROOT / "client" / "src" / "content" / "systematic_review.mdx",
            ROOT / "server" / "app" / "helpers" / "templates" / "project_invite.html",
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
    assert "sync-pdf-worker.mjs && node scripts/generate-blog-metadata.mjs" in package
    assert "client/public/pdf.worker.mjs" in ignore


def test_alb_routes_only_reviewed_public_api_prefixes() -> None:
    template = load_template("scholens-production.yml")
    resources = template["Resources"]
    values = resources["ApiListenerRule"]["Properties"]["Conditions"][0][
        "PathPatternConfig"
    ]["Values"]

    assert values == ["/api/v1*", "/webhooks/v1*", "/mcp*", "/admin*"]
    assert all("internal" not in value for value in values)
    assert resources["LoadBalancer"]["Properties"]["Scheme"] == "internet-facing"
    assert resources["WebAcl"]["Properties"]["Rules"][0]["Name"] == (
        "RequireCloudflareOriginToken"
    )


def test_ci_builds_images_and_runs_independent_migrations_twice() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gate_runner = (ROOT / "scripts" / "run-gates.sh").read_text(encoding="utf-8")

    assert "tags: scholens-api:ci" in workflow
    assert "for _ in 1 2; do" in workflow
    assert "sanchezcloud-identity migrate" in workflow
    assert "--entrypoint scholens" in workflow
    assert "db upgrade --yes --json" in workflow
    assert "scholens dev reset-product" in workflow
    assert "RESET-SCHOLENS-LOCAL" in workflow
    assert "account_plan_grants" in workflow
    assert "account_quota_overrides" in workflow
    assert "alembic downgrade b12d7d620e91" in workflow
    assert "WHERE origin_kind = 'cli'" in workflow
    assert "test_postgres_quota_invariants.py" in workflow
    assert "--entrypoint alembic" in workflow
    assert "CREATE TABLE auth.product_migrator_must_not_create" in workflow
    assert "CREATE TABLE scholens.auth_migrator_must_not_create" in workflow

    server_dockerfile = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY --from=builder /app/migrations/ /app/migrations/" in server_dockerfile
    assert "SCHOLENS_SERVER_ROOT=/app" in server_dockerfile

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
    for dependency in (
        "server",
        "jobs",
        "shared-packages",
        "web",
        "client",
        "deployment-contract",
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
