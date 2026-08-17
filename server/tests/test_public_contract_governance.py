from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

from app.transport.mcp.contract_artifacts import OUTPUT, public_mcp_contract

ROOT = Path(__file__).parents[2]


def _script(name: str) -> ModuleType:
    path = ROOT / "scripts" / name
    specification = importlib.util.spec_from_file_location(path.stem, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_public_mcp_snapshot_is_current_and_complete() -> None:
    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))

    assert committed == public_mcp_contract()
    assert committed["endpoint"] == "/mcp"
    assert len(committed["tools"]) == 56
    assert set(committed["tools"]["get_project"]) >= {
        "input_schema",
        "output_schema",
        "required_permission",
        "behavior",
    }


def test_mcp_metadata_checker_rejects_permission_and_safety_regressions() -> None:
    checker = _script("mcp_contract_compatibility.py")
    base = {
        "contract_version": 1,
        "endpoint": "/mcp",
        "protocol": "mcp",
        "tools": {
            "read_paper": {
                "execution": "query",
                "required_permission": "read",
                "confirmation_policy": "none",
                "behavior": {
                    "read_only": True,
                    "destructive": False,
                    "idempotent": True,
                    "open_world": False,
                },
            }
        },
    }
    revision = json.loads(json.dumps(base))
    revision["tools"]["read_paper"]["required_permission"] = "manage"
    revision["tools"]["read_paper"]["behavior"]["destructive"] = True

    assert checker.metadata_breaks(base, revision) == [
        "MCP tool read_paper changed required_permission",
        "MCP tool read_paper changed behavior.destructive",
    ]

    revision = json.loads(json.dumps(base))
    revision["tools"]["read_paper"]["confirmation_policy"] = "required"
    assert checker.metadata_breaks(base, revision) == [
        "MCP tool read_paper changed confirmation_policy"
    ]

    assert checker.metadata_breaks(revision, base) == [
        "MCP tool read_paper changed confirmation_policy"
    ]


def test_mcp_openapi_renderer_rewrites_local_schema_definitions() -> None:
    checker = _script("mcp_contract_compatibility.py")
    contract = {
        "contract_version": 1,
        "tools": {
            "read_paper": {
                "input_schema": {
                    "type": "object",
                    "$defs": {"PaperId": {"type": "string"}},
                    "properties": {"id": {"$ref": "#/$defs/PaperId"}},
                    "discriminator": {
                        "propertyName": "kind",
                        "mapping": {"paper": "#/$defs/PaperId"},
                    },
                },
                "output_schema": {"type": "object", "properties": {}},
            }
        },
    }

    rendered = checker.render_openapi(contract)

    request = rendered["paths"]["/tools/read_paper"]["post"]["requestBody"]
    assert request["content"]["application/json"]["schema"]["properties"]["id"] == {
        "$ref": "#/components/schemas/read_paper_input_PaperId"
    }
    assert rendered["components"]["schemas"]["read_paper_input_PaperId"] == {
        "type": "string"
    }
    assert request["content"]["application/json"]["schema"]["discriminator"][
        "mapping"
    ] == {"paper": "#/components/schemas/read_paper_input_PaperId"}


def test_deprecation_registry_is_machine_readable() -> None:
    checker = _script("deprecation_registry.py")
    registry = json.loads(
        (ROOT / "server/contracts/deprecations.json").read_text(encoding="utf-8")
    )

    assert checker.validation_failures(registry) == []


def test_deprecation_registry_rejects_unowned_or_short_lived_compatibility() -> None:
    checker = _script("deprecation_registry.py")
    registry = {
        "contract_version": 1,
        "entries": [
            {
                "id": "legacy-reader",
                "boundary": "http",
                "target": "GET /api/v1/reader",
                "owner": "",
                "replacement": "GET /api/v2/reader",
                "deprecated_on": "2026-08-17",
                "earliest_removal_on": "2026-09-01",
                "telemetry_key": "http.legacy-reader",
                "zero_traffic_since": None,
                "state": "deprecated",
                "removed_on": None,
                "removal_evidence": None,
            }
        ],
    }

    assert checker.validation_failures(registry) == [
        "deprecation entry 0 has an invalid owner",
        "deprecation entry 0 has a deprecation window shorter than 90 days",
    ]


def test_retired_targets_are_removed_only_from_the_compatibility_baseline() -> None:
    checker = _script("deprecation_registry.py")
    registry = {
        "contract_version": 1,
        "entries": [
            {
                "id": "legacy-reader",
                "boundary": "http",
                "target": "GET /api/v1/reader",
                "owner": "platform",
                "replacement": "GET /api/v2/reader",
                "deprecated_on": "2026-01-01",
                "earliest_removal_on": "2026-04-01",
                "telemetry_key": "http.legacy-reader",
                "zero_traffic_since": "2026-05-01",
                "state": "removed",
                "removed_on": "2026-06-01",
                "removal_evidence": "dashboard://legacy-reader-zero-traffic",
            }
        ],
    }
    base = {
        "paths": {
            "/api/v1/reader": {"get": {"responses": {"200": {"description": "ok"}}}}
        }
    }
    revision = {"paths": {}}

    assert (
        checker.validation_failures(
            registry,
            today=date(2026, 8, 17),
        )
        == []
    )
    assert checker.prepare_http_base(base, revision, registry) == {"paths": {}}
    assert "/api/v1/reader" in base["paths"]


def test_retirement_requires_thirty_zero_traffic_days_and_actual_removal() -> None:
    checker = _script("deprecation_registry.py")
    entry = {
        "id": "legacy-tool",
        "boundary": "mcp",
        "target": "legacy_tool",
        "owner": "platform",
        "replacement": "replacement_tool",
        "deprecated_on": "2026-01-01",
        "earliest_removal_on": "2026-04-01",
        "telemetry_key": "mcp.legacy-tool",
        "zero_traffic_since": "2026-05-15",
        "state": "removed",
        "removed_on": "2026-06-01",
        "removal_evidence": "dashboard://legacy-tool-zero-traffic",
    }
    registry = {"contract_version": 1, "entries": [entry]}

    assert checker.validation_failures(
        registry,
        today=date(2026, 8, 17),
    ) == ["deprecation entry 0 has fewer than 30 consecutive zero-traffic days"]
    entry["zero_traffic_since"] = "2026-05-01"
    empty = {"contract_version": 1, "entries": []}
    assert checker.transition_failures(
        empty,
        registry,
        today=date(2026, 8, 17),
    ) == ["new deprecation must start as deprecated: legacy-tool"]

    deprecated = json.loads(json.dumps(registry))
    deprecated_entry = deprecated["entries"][0]
    deprecated_entry["zero_traffic_since"] = None
    deprecated_entry["state"] = "deprecated"
    deprecated_entry["removed_on"] = None
    deprecated_entry["removal_evidence"] = None
    assert checker.transition_failures(
        deprecated,
        registry,
        today=date(2026, 8, 17),
    ) == ["deprecation legacy-tool must record zero traffic before removal"]

    observed = json.loads(json.dumps(deprecated))
    observed["entries"][0]["zero_traffic_since"] = "2026-05-01"
    assert (
        checker.transition_failures(
            observed,
            registry,
            today=date(2026, 8, 17),
        )
        == []
    )

    changed_observation = json.loads(json.dumps(registry))
    changed_observation["entries"][0]["zero_traffic_since"] = "2026-05-02"
    assert checker.transition_failures(
        observed,
        changed_observation,
        today=date(2026, 8, 17),
    ) == ["deprecation legacy-tool changed zero-traffic evidence during removal"]

    with pytest.raises(ValueError, match="retired MCP target still exists"):
        checker.prepare_mcp_base(
            {"tools": {"legacy_tool": {}}},
            {"tools": {"legacy_tool": {}}},
            registry,
        )


def test_expand_migration_policy_rejects_destructive_operations(
    tmp_path: Path,
) -> None:
    checker = _script("migration_policy_compatibility.py")
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_root.py").write_text(
        'revision = "root"\ndown_revision = None\n',
        encoding="utf-8",
    )
    (versions / "0002_expand.py").write_text(
        'revision = "expand"\ndown_revision = "root"\n'
        "def upgrade():\n"
        '    op.drop_column("papers", "legacy_value")\n'
        '    op.add_column("papers", sa.Column("required", sa.String(), nullable=False))\n'
        '    op.create_unique_constraint("uq_title", "papers", ["title"])\n',
        encoding="utf-8",
    )
    base = {
        "contract_version": 1,
        "production_baseline_revision": "root",
        "revisions": {"root": {"phase": "baseline"}},
    }
    revision = {
        **base,
        "revisions": {
            **base["revisions"],
            "expand": {"phase": "expand"},
        },
    }

    assert checker.compatibility_failures(base, revision, versions=versions) == [
        "0002_expand.py:4 uses op.drop_column",
        "0002_expand.py:5 adds a required column without a server default",
        "0002_expand.py:6 adds a write-restricting constraint",
    ]


def test_expand_migration_policy_rejects_destructive_batch_operations(
    tmp_path: Path,
) -> None:
    checker = _script("migration_policy_compatibility.py")
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_root.py").write_text(
        'revision = "root"\ndown_revision = None\n',
        encoding="utf-8",
    )
    (versions / "0002_expand.py").write_text(
        'revision = "expand"\ndown_revision = "root"\n'
        "def upgrade():\n"
        '    with op.batch_alter_table("papers") as batch_op:\n'
        '        batch_op.drop_column("legacy_value")\n'
        '        batch_op.add_column(sa.Column("required", sa.String(), nullable=False))\n',
        encoding="utf-8",
    )
    base = {
        "contract_version": 1,
        "production_baseline_revision": "root",
        "revisions": {"root": {"phase": "baseline"}},
    }
    revision = {
        **base,
        "revisions": {
            **base["revisions"],
            "expand": {"phase": "expand"},
        },
    }

    assert checker.compatibility_failures(base, revision, versions=versions) == [
        "0002_expand.py:5 uses op.drop_column",
        "0002_expand.py:6 adds a required column without a server default",
    ]
