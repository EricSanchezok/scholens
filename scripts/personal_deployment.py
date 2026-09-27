"""Render isolated EC2 deployment templates from the canonical ECS contracts.

This adapter retains product IAM, secret, queue and storage contracts while
selecting the explicitly reviewed single-host resource set. It never calls AWS.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


class CloudFormationLoader(yaml.SafeLoader):
    pass


def intrinsic(loader: Any, tag: str, node: Any) -> dict[str, Any]:
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    if tag == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {"Ref" if tag == "Ref" else f"Fn::{tag}": value}


CloudFormationLoader.add_multi_constructor("!", intrinsic)

PLATFORM_IMPORTS = {
    "sanchezcloud-production-vpc-id": "VpcId",
    "sanchezcloud-production-vpc-cidr": "VpcCidr",
    "sanchezcloud-production-cluster-arn": "ClusterArn",
    "sanchezcloud-production-cluster-name": "ClusterName",
    "sanchezcloud-production-private-subnet-1": "SubnetId",
    "sanchezcloud-production-private-subnet-2": "SubnetId",
    "sanchezcloud-scholight-mcp-delegation-secret-arn": "ScholightMcpDelegationSecretArn",
}


def adapt(value: Any) -> Any:
    if isinstance(value, dict):
        imported = value.get("Fn::ImportValue")
        if isinstance(imported, str) and imported in PLATFORM_IMPORTS:
            return {"Ref": PLATFORM_IMPORTS[imported]}
        if value.get("Key") == "Environment":
            return {"Key": "Environment", "Value": "preview"}
        return {key: adapt(item) for key, item in value.items()}
    if isinstance(value, list):
        return [adapt(item) for item in value]
    if isinstance(value, str):
        return (
            value.replace("/production/", "/preview/")
            .replace("scholens-production-", "scholens-preview-")
            .replace("task/sanchezcloud-production/", "task/${ClusterName}/")
            .replace(
                ":environment:image-publish", ":environment:personal-image-publish"
            )
            .replace(
                ":environment:database-production", ":environment:personal-database"
            )
            .replace(
                ":environment:infrastructure-production",
                ":environment:personal-infrastructure",
            )
            .replace(":environment:production", ":environment:personal-preview")
        )
    return value


def common(template: dict[str, Any]) -> dict[str, Any]:
    template = adapt(template)
    parameters = template.setdefault("Parameters", {})
    for name in set(PLATFORM_IMPORTS.values()):
        parameters.setdefault(name, {"Type": "String"})
    parameters.update(
        {
            "ExpectedAccountId": {"Type": "String", "AllowedPattern": "[0-9]{12}"},
            "HostSecurityGroupId": {"Type": "AWS::EC2::SecurityGroup::Id"},
        }
    )
    template["Rules"] = {
        "ExpectedAccount": {
            "Assertions": [
                {
                    "Assert": {
                        "Fn::Equals": [
                            {"Ref": "AWS::AccountId"},
                            {"Ref": "ExpectedAccountId"},
                        ]
                    },
                    "AssertDescription": "Only the reviewed destination account is allowed.",
                }
            ]
        }
    }
    return template


def foundation(template: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "AWS::KMS::Key",
        "AWS::KMS::Alias",
        "AWS::S3::Bucket",
        "AWS::S3::BucketPolicy",
        "AWS::ECR::Repository",
        "AWS::SQS::Queue",
        "AWS::SecretsManager::Secret",
        "AWS::SNS::Topic",
        "AWS::SNS::Subscription",
    }
    template["Resources"] = {
        k: v for k, v in template["Resources"].items() if v["Type"] in allowed
    }
    template["Parameters"]["ProductionDomain"]["Default"] = (
        "scholens-preview.sanchezcloud.net"
    )
    outputs = template["Outputs"]
    outputs["ApplicationSecurityGroupId"]["Value"] = {"Ref": "HostSecurityGroupId"}
    outputs["CacheEndpointAddress"]["Value"] = "cache.personal.svc.sanchezcloud"
    outputs["CacheEndpointPort"]["Value"] = "6380"
    for name in ("DatabaseRuntimeSecret", "DatabaseMigratorSecret"):
        generation = template["Resources"][name]["Properties"]["GenerateSecretString"]
        fields = json.loads(generation["SecretStringTemplate"])
        fields["host"] = "postgres.personal.svc.sanchezcloud"
        generation["SecretStringTemplate"] = json.dumps(fields)
    return template


def bootstrap(template: dict[str, Any]) -> dict[str, Any]:
    template["Parameters"]["RdsSecurityGroupId"].pop("Default", None)
    template["Parameters"]["BackgroundHostRoleArn"] = {
        "Type": "String",
        "AllowedPattern": r"^arn:aws:iam::[0-9]{12}:role/sanchezcloud-personal-foundation-HostRole-[A-Za-z0-9]+$",
    }
    registrations = [
        {
            "Fn::Sub": "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/sanchezcloud/personal/background/scholens-"
            + name
        }
        for name in (
            "document",
            "document-index",
            "document-enrichment",
            "research",
            "maintenance",
        )
    ]
    region = {"StringEquals": {"aws:RequestedRegion": {"Ref": "AWS::Region"}}}
    template["Resources"]["ProductionDeployRole"]["Properties"]["Policies"].append(
        {
            "PolicyName": "CoordinateProductAdmission",
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "cloudformation:CreateChangeSet",
                            "cloudformation:DescribeChangeSet",
                            "cloudformation:ExecuteChangeSet",
                            "cloudformation:DescribeStacks",
                            "cloudformation:GetTemplate",
                        ],
                        "Resource": {
                            "Fn::Sub": "arn:aws:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/scholens-personal-background/*"
                        },
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["ssm:GetParameter", "ssm:GetParameters"],
                        "Resource": registrations
                        + [
                            {
                                "Fn::Sub": "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/sanchezcloud/personal/admission-status"
                            }
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["ecs:ListTasks", "ecs:DescribeTaskDefinition"],
                        "Resource": "*",
                        "Condition": region,
                    },
                    {
                        "Effect": "Allow",
                        "Action": "ecs:DescribeTasks",
                        "Resource": {
                            "Fn::Sub": "arn:aws:ecs:${AWS::Region}:${AWS::AccountId}:task/${ClusterName}/*"
                        },
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject", "s3:PutObject"],
                        "Resource": {
                            "Fn::Sub": "arn:aws:s3:::sanchezcloud-scholens-releases-${AWS::AccountId}-${AWS::Region}/cloudformation/personal/releases/*"
                        },
                    },
                ],
            },
        }
    )
    template["Resources"]["RuntimeCloudFormationServiceRole"]["Properties"][
        "Policies"
    ] = [
        {
            "PolicyName": "ManageProductAdmissionRegistration",
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ssm:PutParameter",
                            "ssm:GetParameter",
                            "ssm:AddTagsToResource",
                            "ssm:RemoveTagsFromResource",
                            "ssm:ListTagsForResource",
                        ],
                        "Resource": registrations,
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "iam:GetRole",
                            "iam:GetRolePolicy",
                            "iam:PutRolePolicy",
                            "iam:DeleteRolePolicy",
                        ],
                        "Resource": {"Ref": "BackgroundHostRoleArn"},
                    },
                ],
            },
        }
    ]

    # Each derived process has an independent, explicitly allowlisted task role.
    def add_process_roles(value: Any) -> None:
        if isinstance(value, dict):
            resources = value.get("Resource")
            if isinstance(resources, list):
                for item in list(resources):
                    arn = item.get("Fn::Sub", "") if isinstance(item, dict) else ""
                    if isinstance(arn, str) and arn.endswith(
                        ":role/SanchezCloudScholensApiTaskRole"
                    ):
                        resources.append(
                            {
                                "Fn::Sub": arn.replace(
                                    "ApiTaskRole", "ConversationWorkerTaskRole"
                                )
                            }
                        )
                    if isinstance(arn, str) and arn.endswith(
                        ":role/SanchezCloudScholensDocumentWorkerTaskRole"
                    ):
                        resources.extend(
                            {"Fn::Sub": arn.replace("DocumentWorker", stage + "Worker")}
                            for stage in ("DocumentIndex", "DocumentEnrichment")
                        )
            for child in value.values():
                add_process_roles(child)
        elif isinstance(value, list):
            for child in value:
                add_process_roles(child)

    add_process_roles(template)
    return template


LIMITS = {
    "web": (64, 256, 512),
    "api": (128, 768, 1536),
    "conversation-worker": (128, 512, 1536),
    "document-worker": (256, 512, 1280),
    "document-index-worker": (128, 384, 1024),
    "document-enrichment-worker": (128, 384, 1024),
    "research-worker": (128, 384, 768),
    "maintenance-worker": (64, 256, 512),
    "migration": (128, 256, 512),
    "scheduler": (64, 128, 256),
}


def document_stage_resources(resources: dict[str, Any]) -> None:
    """Reuse the canonical worker capabilities with a single-queue IAM boundary."""
    for prefix, queue in (
        ("DocumentIndex", "document-index"),
        ("DocumentEnrichment", "document-enrichment"),
    ):
        role = copy.deepcopy(resources["DocumentWorkerTaskRole"])
        role["Properties"]["RoleName"] = (
            "SanchezCloudScholens" + prefix + "WorkerTaskRole"
        )
        policy = role["Properties"]["Policies"][0]
        policy["PolicyName"] = prefix + "WorkerDataPlane"
        for statement in policy["PolicyDocument"]["Statement"]:
            if "sqs:ReceiveMessage" in statement.get("Action", []):
                statement["Resource"] = {
                    "Fn::ImportValue": "sanchezcloud-scholens-" + queue + "-queue-arn"
                }
        resources[prefix + "WorkerTaskRole"] = role
        log = copy.deepcopy(resources["DocumentLogGroup"])
        log["Properties"]["LogGroupName"] = (
            "/sanchezcloud/scholens/" + queue + "-worker"
        )
        resources[prefix + "LogGroup"] = log
        task = copy.deepcopy(resources["DocumentWorkerTaskDefinition"])
        props = task["Properties"]
        props["Family"] = "sanchezcloud-scholens-" + queue + "-worker"
        props["TaskRoleArn"] = {"Fn::GetAtt": [prefix + "WorkerTaskRole", "Arn"]}
        worker = props["ContainerDefinitions"][0]
        worker["Name"] = queue + "-worker"
        worker["Command"] = [
            "--queues=" + queue if item == "--queues=document" else item
            for item in worker["Command"]
        ]
        worker["LogConfiguration"]["Options"].update(
            {
                "awslogs-group": {"Ref": prefix + "LogGroup"},
                "awslogs-stream-prefix": queue,
            }
        )
        resources[prefix + "WorkerTaskDefinition"] = task
        service = copy.deepcopy(resources["DocumentWorkerService"])
        service["Properties"]["ServiceName"] = "scholens-" + queue + "-worker"
        service["Properties"]["TaskDefinition"] = {
            "Ref": prefix + "WorkerTaskDefinition"
        }
        resources[prefix + "WorkerService"] = service


INFERENCE_VOLUME = {
    "Name": "inference",
    "Host": {"SourcePath": "/srv/sanchezcloud/scholens-inference"},
}
INFERENCE_SOCKET = "/run/scholens-inference/model.sock"


def inference_resources(resources: dict[str, Any]) -> None:
    """One warmed model, no AWS role, no TCP listener or outbound network."""
    mount = {
        "SourceVolume": "inference",
        "ContainerPath": "/run/scholens-inference",
        "ReadOnly": False,
    }
    resources["InferenceLogGroup"] = {
        "Type": "AWS::Logs::LogGroup",
        "Properties": {
            "LogGroupName": "/sanchezcloud/scholens/inference",
            "RetentionInDays": 7,
        },
    }
    resources["InferenceTaskDefinition"] = {
        "Type": "AWS::ECS::TaskDefinition",
        "Properties": {
            "Family": "sanchezcloud-scholens-inference",
            "NetworkMode": "none",
            "RequiresCompatibilities": ["EC2"],
            "RuntimePlatform": {
                "CpuArchitecture": "ARM64",
                "OperatingSystemFamily": "LINUX",
            },
            "ExecutionRoleArn": {
                "Fn::ImportValue": "sanchezcloud-scholens-task-execution-role-arn"
            },
            "Volumes": [copy.deepcopy(INFERENCE_VOLUME)],
            "ContainerDefinitions": [
                {
                    "Name": "inference",
                    "Image": {"Ref": "ApiImage"},
                    "Essential": True,
                    "User": "1000:1000",
                    "Cpu": 128,
                    "MemoryReservation": 512,
                    "Memory": 1024,
                    "ReadonlyRootFilesystem": True,
                    "StopTimeout": 30,
                    "EntryPoint": ["python", "-m", "scholens_ai.inference"],
                    "Command": [],
                    "LinuxParameters": {
                        "InitProcessEnabled": True,
                        "Capabilities": {"Drop": ["ALL"]},
                    },
                    "MountPoints": [mount],
                    "DependsOn": [
                        {"ContainerName": "inference-init", "Condition": "SUCCESS"}
                    ],
                    "Environment": [
                        {
                            "Name": "SCHOLENS_EMBEDDING_SOCKET",
                            "Value": INFERENCE_SOCKET,
                        },
                        {"Name": "SCHOLENS_EMBEDDING_THREADS", "Value": "1"},
                    ],
                    "HealthCheck": {
                        "Command": [
                            "CMD",
                            "python",
                            "-m",
                            "scholens_ai.inference",
                            "--check",
                        ],
                        "Interval": 30,
                        "Timeout": 5,
                        "Retries": 3,
                        "StartPeriod": 60,
                    },
                    "LogConfiguration": {
                        "LogDriver": "awslogs",
                        "Options": {
                            "awslogs-region": {"Ref": "AWS::Region"},
                            "awslogs-group": {"Ref": "InferenceLogGroup"},
                            "awslogs-stream-prefix": "inference",
                        },
                    },
                },
                {
                    "Name": "inference-init",
                    "Image": {"Ref": "ApiImage"},
                    "Essential": False,
                    "User": "0",
                    "Cpu": 0,
                    "MemoryReservation": 32,
                    "Memory": 64,
                    "ReadonlyRootFilesystem": True,
                    "EntryPoint": ["python", "-c"],
                    "Command": [
                        "import os; p='/run/scholens-inference'; os.chmod(p, 0o770); os.chown(p, 1000, 1000)"
                    ],
                    "LinuxParameters": {
                        "Capabilities": {"Drop": ["ALL"], "Add": ["CHOWN", "FOWNER"]}
                    },
                    "MountPoints": [copy.deepcopy(mount)],
                },
            ],
        },
    }
    service = copy.deepcopy(resources["DocumentWorkerService"])
    service["Properties"].update(
        {
            "ServiceName": "scholens-inference",
            "TaskDefinition": {"Ref": "InferenceTaskDefinition"},
            "DesiredCount": {"Fn::If": ["RunSharedInference", 1, 0]},
        }
    )
    resources["InferenceService"] = service


def runtime(template: dict[str, Any]) -> dict[str, Any]:
    kept_types = {
        "AWS::IAM::Role",
        "AWS::Logs::LogGroup",
        "AWS::ECS::TaskDefinition",
        "AWS::ECS::Service",
    }
    resources = {
        k: v
        for k, v in template["Resources"].items()
        if v["Type"] in kept_types
        and k not in {"SchedulerInvocationRole", "MetricsLogGroup", "WafLogGroup"}
    }
    document_stage_resources(resources)
    resources["ConversationWorkerTaskRole"] = copy.deepcopy(resources["ApiTaskRole"])
    resources["ConversationWorkerTaskRole"]["Properties"]["RoleName"] = (
        "SanchezCloudScholensConversationWorkerTaskRole"
    )
    resources["ConversationWorkerTaskDefinition"]["Properties"]["TaskRoleArn"] = {
        "Fn::GetAtt": ["ConversationWorkerTaskRole", "Arn"]
    }
    template["Resources"] = resources
    template["Parameters"]["DomainName"]["Default"] = (
        "scholens-preview.sanchezcloud.net"
    )
    template["Parameters"]["ScholightMcpUrl"] = {
        "Type": "String",
        "AllowedPattern": "https://.+/api/mcp",
    }
    template["Parameters"]["ApplicationEnabled"]["Default"] = "false"
    template["Parameters"]["BackgroundMode"] = {
        "Type": "String",
        "Default": "resident",
        "AllowedValues": ["resident", "admitted"],
    }
    template["Parameters"]["SharedInferenceEnabled"] = {
        "Type": "String",
        "Default": "false",
        "AllowedValues": ["false", "true"],
    }
    for flag in (
        "JobResultInboxEnabled",
        "DocumentPipelineEnabled",
        "JobDispatchFairnessEnabled",
    ):
        template["Parameters"][flag] = {
            "Type": "String",
            "Default": "false",
            "AllowedValues": ["false", "true"],
        }
    template["Parameters"]["DocumentPipelinePercent"] = {
        "Type": "Number",
        "Default": 0,
        "AllowedValues": [0, 10, 50, 100],
    }
    template["Rules"]["EnabledApplicationRequiresSharedInference"] = {
        "Assertions": [
            {
                "Assert": {
                    "Fn::Or": [
                        {"Fn::Equals": [{"Ref": "ApplicationEnabled"}, "false"]},
                        {"Fn::Equals": [{"Ref": "SharedInferenceEnabled"}, "true"]},
                    ]
                },
                "AssertDescription": "Enabled tokenizer-only workers require the shared model owner and its measured memory budget.",
            }
        ]
    }
    template["Rules"]["DocumentStageConsumers"] = {
        "Assertions": [
            {
                "Assert": {
                    "Fn::Or": [
                        {"Fn::Equals": [{"Ref": "DocumentPipelineEnabled"}, "false"]},
                        {
                            "Fn::And": [
                                {
                                    "Fn::Equals": [
                                        {"Ref": "JobResultInboxEnabled"},
                                        "true",
                                    ]
                                },
                                {
                                    "Fn::Equals": [
                                        {"Ref": "SharedInferenceEnabled"},
                                        "true",
                                    ]
                                },
                            ]
                        },
                    ]
                },
                "AssertDescription": "Document stage producers require both durable receipt consumers and shared inference.",
            }
        ]
    }
    template["Conditions"]["SharedInference"] = {
        "Fn::Equals": [{"Ref": "SharedInferenceEnabled"}, "true"]
    }
    template["Conditions"]["RunSharedInference"] = {
        "Fn::And": [{"Condition": "RunApplication"}, {"Condition": "SharedInference"}]
    }
    template["Conditions"]["AdmittedBackground"] = {
        "Fn::Equals": [{"Ref": "BackgroundMode"}, "admitted"]
    }
    template["Conditions"]["RunResidentBackground"] = {
        "Fn::And": [
            {"Condition": "RunApplication"},
            {"Fn::Not": [{"Condition": "AdmittedBackground"}]},
        ]
    }
    background = {
        "document-worker",
        "document-index-worker",
        "document-enrichment-worker",
        "research-worker",
        "maintenance-worker",
    }
    template["Parameters"]["EmailDeliveryEnabled"] = {
        "Type": "String",
        "Default": "false",
        "AllowedValues": ["false", "true"],
        "Description": "Enable real email only after the reviewed production cutover.",
    }
    for name, resource in resources.items():
        kind, props = resource["Type"], resource["Properties"]
        resource.pop("DependsOn", None)
        if kind == "AWS::IAM::Role":
            props["ManagedPolicyArns"] = [
                p
                for p in props.get("ManagedPolicyArns", [])
                if p != {"Ref": "TelemetryPolicy"}
            ]
            if not props["ManagedPolicyArns"]:
                props.pop("ManagedPolicyArns")
        elif kind == "AWS::Logs::LogGroup":
            props["RetentionInDays"] = 7
        elif kind == "AWS::ECS::Service":
            for key in (
                "CapacityProviderStrategy",
                "NetworkConfiguration",
                "LoadBalancers",
                "ServiceRegistries",
                "HealthCheckGracePeriodSeconds",
            ):
                props.pop(key, None)
            props["LaunchType"] = "EC2"
            props["DesiredCount"] = {"Fn::If": ["RunApplication", 1, 0]}
            if name in {
                "DocumentWorkerService",
                "DocumentIndexWorkerService",
                "DocumentEnrichmentWorkerService",
                "ResearchWorkerService",
                "MaintenanceWorkerService",
            }:
                props["DesiredCount"] = {"Fn::If": ["RunResidentBackground", 1, 0]}
            props["DeploymentConfiguration"].update(
                {"MinimumHealthyPercent": 0, "MaximumPercent": 100}
            )
        elif kind == "AWS::ECS::TaskDefinition":
            for key in ("Cpu", "Memory", "EphemeralStorage"):
                props.pop(key, None)
            props["NetworkMode"] = "bridge"
            props["RequiresCompatibilities"] = ["EC2"]
            props["RuntimePlatform"]["CpuArchitecture"] = "ARM64"
            props.setdefault("Volumes", []).append(
                {"Name": "trust", "Host": {"SourcePath": "/srv/sanchezcloud/trust"}}
            )
            if name not in {
                "WebTaskDefinition",
                "MigrationTaskDefinition",
                "SchedulerTaskDefinition",
            }:
                props["Volumes"].append(copy.deepcopy(INFERENCE_VOLUME))
            containers = [
                c for c in props["ContainerDefinitions"] if c["Name"] != "adot"
            ]
            props["ContainerDefinitions"] = containers
            for container in containers:
                if container["Name"] == "tmp-init":
                    container.update({"Cpu": 0, "MemoryReservation": 32, "Memory": 64})
                    continue
                cpu, reserved, maximum = LIMITS[container["Name"]]
                container.update(
                    {"Cpu": cpu, "MemoryReservation": reserved, "Memory": maximum}
                )
                container["DependsOn"] = [
                    d
                    for d in container.get("DependsOn", [])
                    if d["ContainerName"] != "adot"
                ]
                if not container["DependsOn"]:
                    container.pop("DependsOn")
                for port in container.get("PortMappings", []):
                    port["HostPort"] = 13000 if container["Name"] == "web" else 18000
                    port.pop("AppProtocol", None)
                if container["Name"] == "web":
                    continue
                shared_client = any(v["Name"] == "inference" for v in props["Volumes"])
                if shared_client:
                    container.setdefault("MountPoints", []).append(
                        {
                            "SourceVolume": "inference",
                            "ContainerPath": "/run/scholens-inference",
                            "ReadOnly": True,
                        }
                    )
                    if container["Name"] in background:
                        container["User"] = "65532:1000"
                container.setdefault("MountPoints", []).append(
                    {
                        "SourceVolume": "trust",
                        "ContainerPath": "/run/trust",
                        "ReadOnly": True,
                    }
                )
                env = {
                    e["Name"]: e["Value"]
                    for e in container.get("Environment", [])
                    if not e["Name"].startswith("OTEL_")
                }
                env.update(
                    {
                        "RUNTIME_DEPLOYMENT_MODE": "single-host",
                        "SCHOLENS_EMAIL_DELIVERY_ENABLED": {
                            "Ref": "EmailDeliveryEnabled"
                        },
                        "WEB_CONCURRENCY": "1",
                        "AUTH_PG_SSL_ROOT_CERT": "/run/trust/private-ca.pem",
                        "SSL_CERT_FILE": "/run/trust/combined-ca.pem",
                        "WEBHOOK_BASE_URL": "http://host.personal.svc.sanchezcloud:18000",
                        "DIAGNOSTIC_SUCCESS_SAMPLE_RATE": "0",
                        "TRUST_CLOUDFLARE_CLIENT_IP": "false",
                    }
                )
                if shared_client:
                    env["SCHOLENS_EMBEDDING_SOCKET"] = {
                        "Fn::If": ["SharedInference", INFERENCE_SOCKET, ""]
                    }
                if container["Name"] in {"api", "conversation-worker", "scheduler"}:
                    env.update(
                        {
                            "JOB_RESULT_INBOX_ENABLED": {
                                "Ref": "JobResultInboxEnabled"
                            },
                            "DOCUMENT_PIPELINE_ENABLED": {
                                "Ref": "DocumentPipelineEnabled"
                            },
                            "DOCUMENT_PIPELINE_PERCENT": {
                                "Ref": "DocumentPipelinePercent"
                            },
                            "JOB_DISPATCH_FAIRNESS_ENABLED": {
                                "Ref": "JobDispatchFairnessEnabled"
                            },
                        }
                    )
                if container["Name"].endswith("-worker"):
                    env["SCHOLENS_WORKER_HEARTBEAT_FILE"] = "/tmp/worker-heartbeat"
                    container["HealthCheck"] = {
                        "Command": [
                            "CMD",
                            "python",
                            "-m",
                            "scholens_observability.worker_health",
                        ],
                        "Interval": 30,
                        "Timeout": 5,
                        "Retries": 3,
                        "StartPeriod": 90,
                    }
                if container["Name"] in background:
                    env["SCHOLENS_WORKER_ONE_SHOT"] = {
                        "Fn::If": ["AdmittedBackground", "1", "0"]
                    }
                if container["Name"] in {
                    "document-worker",
                    "document-index-worker",
                    "document-enrichment-worker",
                }:
                    env["SCHOLENS_WORKER_MAX_TASKS"] = "5"
                    env["SCHOLENS_WORKER_MAX_SECONDS"] = "300"
                    env["SCHOLENS_EMBEDDING_THREADS"] = "1"
                if "SCHOLIGHT_MCP_URL" in env:
                    env["SCHOLIGHT_MCP_URL"] = {"Ref": "ScholightMcpUrl"}
                for limit in (
                    "AI_MAX_INTERACTIVE_PER_USER",
                    "AI_MAX_BACKGROUND_PER_USER",
                    "AI_MAX_AUDIO_PER_USER",
                ):
                    if limit in env:
                        env[limit] = "1"
                container["Environment"] = [
                    {"Name": k, "Value": v} for k, v in env.items()
                ]
    inference_resources(resources)
    template["Outputs"] = {
        name: {"Value": {"Ref": name}}
        for name, r in resources.items()
        if r["Type"] in {"AWS::ECS::TaskDefinition", "AWS::ECS::Service"}
    }
    return template


def prune_parameters(template: dict[str, Any]) -> None:
    # Parameters are generated only for retained references, including Fn::Sub variables.
    import re

    body = json.dumps({k: v for k, v in template.items() if k != "Parameters"})
    used = set(re.findall(r'"Ref":\s*"([^"]+)"', body)) | set(
        re.findall(r"\$\{([A-Za-z0-9]+)\}", body)
    )
    template["Parameters"] = {
        k: v for k, v in template["Parameters"].items() if k in used
    }


def render(stage: str) -> dict[str, Any]:
    source = {
        "foundation": "foundation",
        "bootstrap": "foundation-bootstrap",
        "runtime": "production",
    }[stage]
    template = yaml.load(
        (ROOT / f"deploy/ecs/scholens-{source}.yml").read_text(),
        Loader=CloudFormationLoader,
    )
    template = common(template)
    template = {"foundation": foundation, "bootstrap": bootstrap, "runtime": runtime}[
        stage
    ](template)
    template["Description"] = f"Isolated personal-account Scholens {stage}"
    prune_parameters(template)
    return template


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["foundation", "bootstrap", "runtime"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(render(args.stage), indent=2) + "\n")
