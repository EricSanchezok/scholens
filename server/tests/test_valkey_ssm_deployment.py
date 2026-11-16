"""Valkey credential migration keeps storage, trust and plaintext consumers stable."""

from __future__ import annotations

import copy
import importlib.util
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "valkey_personal_loader", ROOT / "scripts/personal_deployment.py"
)
assert spec and spec.loader
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)

ACCOUNT = "669409472143"
API_PARAMETER = (
    f"arn:aws:ssm:ap-south-2:{ACCOUNT}:parameter/sanchezcloud/scholens/preview/"
    "cache-api/11111111-2222-3333-4444-555555555555/password"
)
JOBS_PARAMETER = API_PARAMETER.replace("cache-api/", "cache-jobs/")
KEY = f"arn:aws:kms:ap-south-2:{ACCOUNT}:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
IMPORTS = {
    "sanchezcloud-scholens-api-cache-secret-arn": (
        f"arn:aws:secretsmanager:ap-south-2:{ACCOUNT}:secret:synthetic-api-AbCdEf"
    ),
    "sanchezcloud-scholens-jobs-cache-secret-arn": (
        f"arn:aws:secretsmanager:ap-south-2:{ACCOUNT}:secret:synthetic-jobs-AbCdEf"
    ),
    "sanchezcloud-scholens-configuration-key-arn": KEY,
}
NO_VALUE = object()


def template():
    return yaml.load(
        (ROOT / "deploy/personal/valkey/runtime.yml").read_text(),
        Loader=renderer.CloudFormationLoader,
    )


def resolve(value, parameters, conditions):
    if isinstance(value, list):
        return [
            item
            for v in value
            if (item := resolve(v, parameters, conditions)) is not NO_VALUE
        ]
    if not isinstance(value, dict):
        return value
    if set(value) == {"Ref"}:
        return (
            NO_VALUE
            if value["Ref"] == "AWS::NoValue"
            else parameters.get(value["Ref"], "synthetic-reference-" + value["Ref"])
        )
    if set(value) == {"Fn::Equals"}:
        a, b = resolve(value["Fn::Equals"], parameters, conditions)
        return a == b
    if set(value) == {"Fn::Not"}:
        return not resolve(value["Fn::Not"][0], parameters, conditions)
    if set(value) == {"Fn::And"}:
        return all(resolve(value["Fn::And"], parameters, conditions))
    if set(value) == {"Fn::Or"}:
        return any(resolve(value["Fn::Or"], parameters, conditions))
    if set(value) == {"Fn::If"}:
        name, yes, no = value["Fn::If"]
        return resolve(yes if conditions[name] else no, parameters, conditions)
    if set(value) == {"Fn::ImportValue"}:
        return IMPORTS[value["Fn::ImportValue"]]
    if set(value) == {"Fn::GetAtt"}:
        return "synthetic-resource-arn"
    if set(value) == {"Fn::Sub"}:
        sub = value["Fn::Sub"]
        text, replacements = (sub, {}) if isinstance(sub, str) else sub
        replacements = {
            **parameters,
            **resolve(replacements, parameters, conditions),
        }
        return re.sub(r"\$\{([^}]+)\}", lambda m: replacements[m[1]], text)
    return {k: resolve(v, parameters, conditions) for k, v in value.items()}


def render(source="secretsmanager", configured=False):
    body = template()
    parameters = {
        name: spec.get("Default", "synthetic-input")
        for name, spec in body["Parameters"].items()
    }
    parameters.update(
        {
            "AWS::AccountId": ACCOUNT,
            "AWS::Region": "ap-south-2",
            "ExpectedAccountId": ACCOUNT,
            "CacheCredentialSource": source,
        }
    )
    if configured:
        parameters.update(
            ApiCachePasswordParameterArn=API_PARAMETER,
            JobsCachePasswordParameterArn=JOBS_PARAMETER,
        )
    conditions = {
        name: resolve(value, parameters, {})
        for name, value in body["Conditions"].items()
    }
    return resolve(body["Resources"], parameters, conditions)


def statements(resources):
    return resources["ExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"][
        "Statement"
    ]


def test_default_keeps_existing_sm_references_without_ssm_permission():
    resources = render()
    assert template()["Parameters"]["CacheCredentialSource"]["Default"] == (
        "secretsmanager"
    )
    secrets = resources["CacheTask"]["Properties"]["ContainerDefinitions"][0]["Secrets"]
    assert [s["ValueFrom"] for s in secrets] == [
        IMPORTS["sanchezcloud-scholens-api-cache-secret-arn"] + ":password::",
        IMPORTS["sanchezcloud-scholens-jobs-cache-secret-arn"] + ":password::",
    ]
    assert not any("ssm:GetParameters" in s["Action"] for s in statements(resources))


def test_grants_can_be_configured_before_explicit_reference_switch():
    default = render()
    grant_stage = render(configured=True)
    assert grant_stage["CacheTask"] == default["CacheTask"]
    assert grant_stage["CacheService"] == default["CacheService"]
    assert statements(grant_stage)[:3] == statements(default)
    assert len(statements(grant_stage)) == 5


def test_ssm_grants_have_exact_targets_key_and_service_context():
    resources = render("ssm", configured=True)
    new = statements(resources)[3:]
    assert new == [
        {
            "Effect": "Allow",
            "Action": ["ssm:GetParameters"],
            "Resource": [API_PARAMETER, JOBS_PARAMETER],
        },
        {
            "Effect": "Allow",
            "Action": ["kms:Decrypt"],
            "Resource": KEY,
            "Condition": {
                "StringEquals": {
                    "kms:ViaService": "ssm.ap-south-2.amazonaws.com",
                    "kms:EncryptionContext:PARAMETER_ARN": [
                        API_PARAMETER,
                        JOBS_PARAMETER,
                    ],
                }
            },
        },
    ]
    assert statements(resources)[:3] == statements(render())


def test_switch_changes_only_two_credential_sources_and_scoped_grants():
    old = render()
    new = render("ssm", configured=True)
    assert new["CacheTask"]["Properties"]["ContainerDefinitions"][0]["Secrets"] == [
        {"Name": "CACHE_API_PASSWORD", "ValueFrom": API_PARAMETER},
        {"Name": "CACHE_JOBS_PASSWORD", "ValueFrom": JOBS_PARAMETER},
    ]
    normalized = copy.deepcopy(new)
    normalized["CacheTask"]["Properties"]["ContainerDefinitions"][0]["Secrets"] = old[
        "CacheTask"
    ]["Properties"]["ContainerDefinitions"][0]["Secrets"]
    normalized["ExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"][
        "Statement"
    ] = statements(old)
    assert normalized == old


@pytest.mark.parametrize(
    ("source", "api", "jobs", "expected"),
    [
        ("secretsmanager", "", "", True),
        ("ssm", API_PARAMETER, JOBS_PARAMETER, True),
        ("secretsmanager", API_PARAMETER, JOBS_PARAMETER, True),
        ("ssm", "", "", False),
        ("ssm", API_PARAMETER, "", False),
        ("secretsmanager", API_PARAMETER, "", False),
    ],
)
def test_rules_reject_empty_ssm_selection_and_partial_password_pair(
    source, api, jobs, expected
):
    parameters = {
        "AWS::AccountId": ACCOUNT,
        "ExpectedAccountId": ACCOUNT,
        "CacheCredentialSource": source,
        "ApiCachePasswordParameterArn": api,
        "JobsCachePasswordParameterArn": jobs,
    }
    passed = all(
        resolve(assertion["Assert"], parameters, {})
        for rule in template()["Rules"].values()
        if resolve(rule.get("RuleCondition", True), parameters, {})
        for assertion in rule["Assertions"]
    )
    assert passed is expected


@pytest.mark.parametrize(
    "unapproved",
    [
        API_PARAMETER.replace(ACCOUNT, "111122223333"),
        API_PARAMETER.replace("ap-south-2", "us-east-1"),
        API_PARAMETER.replace("/password", "/username"),
        API_PARAMETER.replace("cache-api/", "other-cache/"),
        API_PARAMETER.replace("11111111-2222-3333-4444-555555555555", "*"),
        "arn:aws:ssm:ap-south-2:669409472143:parameter/*",
    ],
)
def test_parameter_schema_excludes_other_accounts_fields_and_wildcards(unapproved):
    pattern = template()["Parameters"]["ApiCachePasswordParameterArn"]["AllowedPattern"]
    assert re.fullmatch(pattern, API_PARAMETER)
    assert re.fullmatch(pattern, "")
    assert not re.fullmatch(pattern, unapproved)
