"""A release must observe the actual controller pause and actual task termination."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "release_admission",
    Path(__file__).resolve().parents[2] / "scripts/release_admission.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_pause_acknowledgement_requires_fresh_loaded_parameter_versions():
    expected = {
        "scholens-document": {
            "parameter_version": 2,
            "enabled": False,
            "task_definition": "task",
        }
    }
    status = {
        "account": module.ACCOUNT,
        "region": module.REGION,
        "cluster": module.CLUSTER,
        "observed_at": 100,
        "registration_refreshed_at": 90,
        "registrations": expected,
    }
    assert module.acknowledged(status, expected, 110)
    for bad in [
        status | {"observed_at": 1},
        status | {"registration_refreshed_at": 0},
        status | {"registrations": {}},
        status | {"account": "919651863140"},
    ]:
        assert not module.acknowledged(bad, expected, 110)


def test_desired_stop_does_not_prove_a_worker_has_exited():
    task = {
        "group": "background:scholens-document",
        "desiredStatus": "STOPPED",
        "lastStatus": "STOPPING",
    }
    assert module.unsettled([task], {"scholens-document"})
    assert not module.unsettled(
        [task | {"lastStatus": "STOPPED"}], {"scholens-document"}
    )
    assert not module.unsettled([task], {"scholight-metadata"})


def test_registration_change_cannot_replace_or_delete_unrelated_resources():
    good = {
        "Changes": [
            {
                "ResourceChange": {
                    "Action": "Modify",
                    "LogicalResourceId": "DocumentRegistration",
                    "Replacement": "False",
                }
            }
        ]
    }
    module.guard_registration_change(good)
    for update in [
        {"Action": "Remove"},
        {"LogicalResourceId": "Database"},
        {"Replacement": "True"},
    ]:
        with pytest.raises(ValueError):
            module.guard_registration_change(
                {
                    "Changes": [
                        {
                            "ResourceChange": good["Changes"][0]["ResourceChange"]
                            | update
                        }
                    ]
                }
            )


def test_registration_expansion_only_adds_the_two_document_stage_registrations():
    for name in ("DocumentIndexRegistration", "DocumentEnrichmentRegistration"):
        change = {
            "Changes": [
                {
                    "ResourceChange": {
                        "Action": "Add",
                        "LogicalResourceId": name,
                        "Replacement": "False",
                    }
                }
            ]
        }
        with pytest.raises(ValueError):
            module.guard_registration_change(change)
        module.guard_registration_change(change, expanding=True)
    for name in ("AdmissionGrant", "ForeignRegistration"):
        with pytest.raises(ValueError):
            module.guard_registration_change(
                {
                    "Changes": [
                        {
                            "ResourceChange": {
                                "Action": "Add",
                                "LogicalResourceId": name,
                            }
                        }
                    ]
                },
                expanding=True,
            )


def test_acknowledgement_accepts_the_existing_topology_before_expansion():
    old = {name + "TaskArn": "task" for name in ("Document", "Research", "Maintenance")}
    assert module.registration_names(old) == {
        "scholens-document",
        "scholens-research",
        "scholens-maintenance",
    }
    new = old | {"DocumentIndexTaskArn": "index", "DocumentEnrichmentTaskArn": "enrich"}
    assert module.registration_names(new) == module.NAMES
    with pytest.raises(ValueError):
        module.registration_names(old | {"DocumentIndexTaskArn": "index"})


def test_first_stage_expansion_submits_new_template_only_while_paused():
    from unittest.mock import MagicMock
    from botocore.exceptions import ClientError

    release = object.__new__(module.AdmissionRelease)
    release.operation = "expand"
    actual = {"Enabled": "false", "DocumentTaskArn": "old"}
    overrides = {"Enabled": "false"}
    for name in module.WORKERS:
        overrides[name + "MemoryMiB"] = "1088"
    for name in ("DocumentIndex", "DocumentEnrichment"):
        for suffix in (
            "TaskArn",
            "TaskRoleArn",
            "ExecutionRoleArn",
            "QueueUrl",
            "QueueArn",
        ):
            overrides[name + suffix] = name + suffix
    planned = actual | overrides
    release.stack = lambda _: {
        "StackStatus": "UPDATE_COMPLETE",
        "Parameters": [
            {"ParameterKey": k, "ParameterValue": v} for k, v in actual.items()
        ],
    }
    release.wait_stack = lambda _: None
    release.cf = MagicMock()
    release.cf.create_change_set.return_value = {"Id": "change"}
    ready = {
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "ChangeSetId": "change",
        "Parameters": [
            {"ParameterKey": k, "ParameterValue": v} for k, v in planned.items()
        ],
        "Changes": [
            {
                "ResourceChange": {
                    "Action": "Add",
                    "LogicalResourceId": "DocumentIndexRegistration",
                }
            }
        ],
    }
    release.cf.describe_change_set.side_effect = [
        ClientError(
            {"Error": {"Code": "ValidationError", "Message": "does not exist"}},
            "DescribeChangeSet",
        ),
        ready,
    ]
    release.change_background("revisions", overrides)
    request = release.cf.create_change_set.call_args.kwargs
    assert "DocumentEnrichmentRegistration:" in request["TemplateBody"]
    assert "UsePreviousTemplate" not in request
    assert {
        p["ParameterKey"]: p["ParameterValue"] for p in request["Parameters"]
    } == planned
    release.cf.execute_change_set.assert_called_once_with(ChangeSetName="change")
    actual["Enabled"] = "true"
    with pytest.raises(ValueError, match="paused"):
        release.change_background("revisions", overrides)


def test_resume_after_ack_failure_does_not_repeat_runtime_or_pause_again():
    release = object.__new__(module.AdmissionRelease)
    release.arn = "change"
    release.operation = "operation"
    records = {
        "start": {"change_set": "change", "restore_enabled": "true"},
        "runtime": {"change_set": "change"},
        "revisions": {"DocumentTaskArn": "new"},
    }
    release.read = records.get
    release.record = lambda name, value: records.update({name: value})
    changes = []
    release.change_background = lambda stage, values: changes.append((stage, values))
    release.wait_ack = lambda: None
    release.run()
    release.run()
    assert changes == [("resume", {"Enabled": "true"})]
    assert "complete" in records


def test_unstarted_plan_expires_or_is_invalidated_by_another_update():
    from datetime import UTC, datetime, timedelta
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from personal_control_plane import guard_plan_freshness

    now = datetime.now(UTC)
    change = {"ExecutionStatus": "AVAILABLE", "CreationTime": now.isoformat()}
    current = {"CreationTime": (now - timedelta(hours=1)).isoformat()}
    guard_plan_freshness(change, current, now)
    with pytest.raises(ValueError, match="expired"):
        guard_plan_freshness(change, current, now + timedelta(days=2))
    with pytest.raises(ValueError, match="changed"):
        guard_plan_freshness(
            change,
            current | {"LastUpdatedTime": (now + timedelta(seconds=1)).isoformat()},
            now,
        )
