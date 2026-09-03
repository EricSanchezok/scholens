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
    assert len(committed["tools"]) == 64
    assert len(committed["resources"]) == 2
    assert len(committed["resource_templates"]) == 4
    assert committed["resource_limits"] == {"max_utf8_bytes": 200_000}
    assert all(
        "anyOf" in resource["output_schema"]
        for collection in ("resources", "resource_templates")
        for resource in committed[collection].values()
    )
    assert all(
        tool["output_schema"].get("type") == "object"
        for tool in committed["tools"].values()
    )
    assert set(committed["tools"]["get_project"]) >= {
        "input_schema",
        "output_schema",
        "required_permission",
        "behavior",
    }
    assert committed["tools"]["get_job"]["execution"] == "query"
    assert (
        committed["tools"]["get_job"]["input_schema"]["properties"]["wait_seconds"][
            "default"
        ]
        == 30
    )
    assert "ingest_papers" in committed["tools"]
    assert "wait_for_jobs" not in committed["tools"]


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

    budgeted = json.loads(json.dumps(base))
    budgeted["tools"]["read_paper"]["max_success_envelope_utf8_bytes"] = 64_000
    reduced = json.loads(json.dumps(budgeted))
    reduced["tools"]["read_paper"]["max_success_envelope_utf8_bytes"] = 32_000
    assert checker.metadata_breaks(budgeted, reduced) == [
        "MCP tool read_paper decreased output byte budget"
    ]

    scoped = json.loads(json.dumps(base))
    scoped["tool_result_limits"] = {
        "unit": "utf8_bytes",
        "scope": "call_tool_result",
        "includes": [
            "content.text",
            "structuredContent",
            "content.resource_link",
        ],
        "excludes": ["jsonrpc", "id"],
    }
    changed_scope = json.loads(json.dumps(scoped))
    changed_scope["tool_result_limits"]["scope"] = "structuredContent"
    assert checker.metadata_breaks(scoped, changed_scope) == [
        "MCP tool result budget scope changed"
    ]


def test_mcp_metadata_checker_guards_resources_and_byte_budget() -> None:
    checker = _script("mcp_contract_compatibility.py")
    base = {
        "contract_version": 1,
        "endpoint": "/mcp",
        "protocol": "mcp",
        "tools": {},
        "resource_limits": {"max_utf8_bytes": 200_000},
        "resources": {
            "scholens://library": {
                "name": "library",
                "mime_type": "application/json",
                "output_schema": {"type": "object"},
            }
        },
        "resource_templates": {
            "scholens://papers/{document_id}": {
                "name": "paper",
                "mime_type": "application/json",
                "output_schema": {"type": "object"},
            }
        },
    }
    revision = json.loads(json.dumps(base))
    revision["resource_limits"]["max_utf8_bytes"] = 100_000
    del revision["resources"]["scholens://library"]
    revision["resource_templates"]["scholens://papers/{document_id}"]["mime_type"] = (
        "text/plain"
    )

    assert checker.metadata_breaks(base, revision) == [
        "MCP resource max_utf8_bytes decreased",
        "MCP resource removed: scholens://library",
        ("MCP resource template scholens://papers/{document_id} changed mime_type"),
    ]

    missing_budget = json.loads(json.dumps(base))
    del missing_budget["resource_limits"]
    assert checker.metadata_breaks(base, missing_budget) == [
        "MCP resource max_utf8_bytes decreased"
    ]


def _empty_public_contracts() -> tuple[dict[str, object], dict[str, object]]:
    return (
        {"contract_version": 1, "endpoint": "/mcp", "protocol": "mcp", "tools": {}},
        {"openapi": "3.1.0", "paths": {}, "components": {"schemas": {}}},
    )


def _schema_correction_entry(
    checker: ModuleType,
    *,
    identifier: str,
    target: str,
    pointer: str,
    value: object,
    boundary: str = "mcp",
    change_kind: str = "one_of_added",
) -> dict[str, object]:
    return {
        "id": identifier,
        "boundary": boundary,
        "target": target,
        "schema_pointer": pointer,
        "change_kind": change_kind,
        "base_value_sha256": None,
        "revision_value_sha256": checker._canonical_sha256(value),
        "owner": "scholens-platform",
        "recorded_on": "2026-08-24",
        "reason": "The runtime validator already enforced this exact constraint.",
        "runtime_evidence": (
            "server/tests/test_workspace_research_outputs.py::"
            "test_update_annotation_thread_runtime_matches_exactly_one_schema"
        ),
    }


def test_schema_corrections_are_exact_and_transition_bound() -> None:
    checker = _script("mcp_contract_compatibility.py")
    base_mcp, http = _empty_public_contracts()
    base_mcp["tools"] = {
        "update_annotation_thread": {"input_schema": {"type": "object"}}
    }
    revision_mcp = json.loads(json.dumps(base_mcp))
    one_of = [{"required": ["color"]}, {"required": ["status"]}]
    revision_mcp["tools"]["update_annotation_thread"]["input_schema"]["oneOf"] = one_of
    empty_registry = {"contract_version": 1, "entries": []}
    entry = _schema_correction_entry(
        checker,
        identifier="mcp-update-annotation-thread-exactly-one",
        target="update_annotation_thread",
        pointer="#/tools/update_annotation_thread/input_schema/oneOf",
        value=one_of,
    )
    registry = {"contract_version": 1, "entries": [entry]}

    assert (
        checker.schema_correction_failures(
            base_registry=empty_registry,
            registry=registry,
            base_mcp=base_mcp,
            revision_mcp=revision_mcp,
            base_http=http,
            revision_http=http,
        )
        == []
    )
    prepared_mcp, prepared_http = checker.prepare_schema_correction_bases(
        registry=registry,
        base_mcp=base_mcp,
        revision_mcp=revision_mcp,
        base_http=http,
        revision_http=http,
    )
    assert "oneOf" not in base_mcp["tools"]["update_annotation_thread"]["input_schema"]
    assert (
        prepared_mcp["tools"]["update_annotation_thread"]["input_schema"]["oneOf"]
        == one_of
    )
    assert prepared_http == http
    tombstone_mcp, tombstone_http = checker.prepare_schema_correction_bases(
        registry=registry,
        base_mcp=revision_mcp,
        revision_mcp=revision_mcp,
        base_http=http,
        revision_http=http,
    )
    assert tombstone_mcp == revision_mcp
    assert tombstone_http == http

    mismatched = json.loads(json.dumps(registry))
    mismatched["entries"][0]["revision_value_sha256"] = "0" * 64
    assert checker.schema_correction_failures(
        base_registry=empty_registry,
        registry=mismatched,
        base_mcp=base_mcp,
        revision_mcp=revision_mcp,
        base_http=http,
        revision_http=http,
    ) == [
        "schema correction revision digest mismatch: mcp "
        "update_annotation_thread "
        "#/tools/update_annotation_thread/input_schema/oneOf (one_of_added)"
    ]

    assert checker.schema_correction_failures(
        base_registry=empty_registry,
        registry=registry,
        base_mcp=revision_mcp,
        revision_mcp=revision_mcp,
        base_http=http,
        revision_http=http,
    ) == [
        "new schema correction does not match the current transition: "
        "mcp-update-annotation-thread-exactly-one"
    ]


def test_schema_correction_checker_rejects_unregistered_unique_items() -> None:
    checker = _script("mcp_contract_compatibility.py")
    base_mcp, http = _empty_public_contracts()
    base_mcp["tools"] = {
        "remove_library_papers": {
            "input_schema": {
                "type": "object",
                "properties": {"document_ids": {"type": "array"}},
            }
        }
    }
    revision_mcp = json.loads(json.dumps(base_mcp))
    revision_mcp["tools"]["remove_library_papers"]["input_schema"]["properties"][
        "document_ids"
    ]["uniqueItems"] = True
    registry = {"contract_version": 1, "entries": []}

    assert checker.schema_correction_failures(
        base_registry=registry,
        registry=registry,
        base_mcp=base_mcp,
        revision_mcp=revision_mcp,
        base_http=http,
        revision_http=http,
    ) == [
        "unregistered restrictive request schema change: mcp "
        "remove_library_papers "
        "#/tools/remove_library_papers/input_schema/properties/document_ids/"
        "uniqueItems (unique_items_enabled)"
    ]


def test_http_schema_corrections_follow_nested_refs() -> None:
    checker = _script("mcp_contract_compatibility.py")
    mcp, base_http = _empty_public_contracts()
    base_http["paths"] = {
        "/api/v1/example": {
            "patch": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Request"}
                        }
                    }
                }
            }
        }
    }
    base_http["components"] = {
        "schemas": {
            "Request": {
                "type": "object",
                "properties": {"metadata": {"$ref": "#/components/schemas/Metadata"}},
            },
            "Metadata": {
                "type": "object",
                "properties": {
                    "authors": {
                        "anyOf": [
                            {"type": "array", "items": {"type": "string"}},
                            {"type": "null"},
                        ]
                    }
                },
            },
        }
    }
    revision_http = json.loads(json.dumps(base_http))
    item_schema = revision_http["components"]["schemas"]["Metadata"]["properties"][
        "authors"
    ]["anyOf"][0]["items"]
    item_schema["minLength"] = 1
    pointer = "#/components/schemas/Metadata/properties/authors/anyOf/0/items/minLength"
    entry = _schema_correction_entry(
        checker,
        identifier="http-example-author-minimum",
        boundary="http",
        target="PATCH /api/v1/example",
        pointer=pointer,
        value=1,
        change_kind="minLength_increased",
    )
    registry = {"contract_version": 1, "entries": [entry]}
    empty_registry = {"contract_version": 1, "entries": []}

    assert (
        checker.schema_correction_failures(
            base_registry=empty_registry,
            registry=registry,
            base_mcp=mcp,
            revision_mcp=mcp,
            base_http=base_http,
            revision_http=revision_http,
        )
        == []
    )
    prepared_mcp, prepared_http = checker.prepare_schema_correction_bases(
        registry=registry,
        base_mcp=mcp,
        revision_mcp=mcp,
        base_http=base_http,
        revision_http=revision_http,
    )
    assert checker._resolve_pointer(base_http, pointer) is checker._MISSING
    assert checker._resolve_pointer(prepared_http, pointer) == 1
    assert prepared_mcp == mcp


def test_repository_schema_correction_registry_is_machine_readable() -> None:
    checker = _script("mcp_contract_compatibility.py")
    registry = json.loads(
        (ROOT / "server/contracts/schema-corrections.json").read_text(encoding="utf-8")
    )

    assert checker.correction_registry_failures(registry) == []


def test_schema_correction_evidence_requires_an_exact_pytest_node() -> None:
    checker = _script("mcp_contract_compatibility.py")
    entry = _schema_correction_entry(
        checker,
        identifier="mcp-update-annotation-thread-exactly-one",
        target="update_annotation_thread",
        pointer="#/tools/update_annotation_thread/input_schema/oneOf",
        value=[{"required": ["color"]}, {"required": ["status"]}],
    )
    entry["runtime_evidence"] = (
        "server/tests/test_workspace_research_outputs.py::"
        "test_update_annotation_thread_runtime_matches_exactly_one"
    )

    assert checker.correction_registry_failures(
        {"contract_version": 1, "entries": [entry]}
    ) == ["schema correction entry 0 has unverifiable runtime_evidence"]


def test_mcp_openapi_renderer_includes_resource_contracts() -> None:
    checker = _script("mcp_contract_compatibility.py")
    contract = {
        "contract_version": 1,
        "tools": {},
        "resources": {
            "scholens://library": {
                "name": "library",
                "mime_type": "application/json",
                "output_schema": {
                    "$defs": {"Paper": {"type": "object"}},
                    "type": "object",
                    "properties": {"paper": {"$ref": "#/$defs/Paper"}},
                },
            }
        },
    }

    rendered = checker.render_openapi(contract)

    response = rendered["paths"]["/resources/static/library"]["get"]["responses"]["200"]
    schema = response["content"]["application/json"]["schema"]
    assert schema["properties"]["paper"] == {
        "$ref": "#/components/schemas/resource_static_library_output_Paper"
    }


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


def test_mcp_openapi_renderer_projects_anyof_onto_success_envelope() -> None:
    checker = _script("mcp_contract_compatibility.py")
    contract = {
        "contract_version": 1,
        "tools": {
            "read_paper": {
                "input_schema": {"type": "object", "properties": {}},
                "output_schema": {
                    "anyOf": [
                        {
                            "$ref": "#/$defs/ReadPaperToolStructuredResult",
                        },
                        {
                            "$ref": "#/$defs/ReadPaperToolErrorResult",
                        },
                    ],
                    "$defs": {
                        "ReadPaperToolStructuredResult": {
                            "type": "object",
                            "properties": {
                                "result": {"$ref": "#/$defs/PaperPayload"},
                                "sources": {"type": "array"},
                            },
                            "required": ["result"],
                        },
                        "ReadPaperToolErrorResult": {
                            "type": "object",
                            "properties": {
                                "error": {
                                    "type": "object",
                                    "properties": {
                                        "code": {"type": "string"},
                                        "message": {"type": "string"},
                                    },
                                    "required": ["code", "message"],
                                }
                            },
                            "required": ["error"],
                        },
                        "PaperPayload": {
                            "type": "object",
                            "properties": {"id": {"type": "string"}},
                            "required": ["id"],
                        },
                    },
                },
            }
        },
    }

    rendered = checker.render_openapi(contract)

    response_schema = rendered["paths"]["/tools/read_paper"]["post"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    # The HTTP 200 projection must be the success envelope only; the error
    # branch (isError transport) must never surface as an HTTP body change.
    assert response_schema["properties"]["result"] == {
        "$ref": "#/components/schemas/read_paper_output_PaperPayload"
    }
    assert response_schema["required"] == ["result"]
    assert "error" not in response_schema["properties"]
    # Reachable $defs are carried over so rendered refs resolve.
    assert "read_paper_output_PaperPayload" in rendered["components"]["schemas"]
    # The unreachable error-branch definition is dropped.
    assert (
        "read_paper_output_ReadPaperToolErrorResult"
        not in rendered["components"]["schemas"]
    )


def test_mcp_openapi_renderer_passes_legacy_single_envelope_through() -> None:
    checker = _script("mcp_contract_compatibility.py")
    contract = {
        "contract_version": 1,
        "tools": {
            "read_paper": {
                "input_schema": {"type": "object", "properties": {}},
                "output_schema": {
                    "type": "object",
                    "properties": {"result": {"type": "object"}},
                    "required": ["result"],
                },
            }
        },
    }

    rendered = checker.render_openapi(contract)

    response_schema = rendered["paths"]["/tools/read_paper"]["post"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert response_schema["required"] == ["result"]
    assert "anyOf" not in response_schema


def test_deprecation_registry_is_machine_readable() -> None:
    checker = _script("deprecation_registry.py")
    registry = json.loads(
        (ROOT / "server/contracts/deprecations.json").read_text(encoding="utf-8")
    )

    assert checker.validation_failures(registry) == []


def test_bounded_mcp_replacements_preserve_owned_legacy_read_contracts() -> None:
    contract = public_mcp_contract()
    registry = json.loads(
        (ROOT / "server/contracts/deprecations.json").read_text(encoding="utf-8")
    )
    expected_replacements = {
        "get_paper": "get_paper_page",
        "get_library_paper": "get_library_paper_page",
        "get_annotation_thread": "get_annotation_thread_page",
        "get_research_output": "get_research_output_page",
        "list_library_papers": "list_library_paper_summaries",
        "list_research_outputs": "list_research_output_summaries",
    }
    registered = {
        entry["target"]: entry["replacement"]
        for entry in registry["entries"]
        if entry["boundary"] == "mcp" and entry["state"] == "deprecated"
    }

    assert expected_replacements.items() <= registered.items()
    assert {
        name: contract["tools"][name]["replacement_tool"]
        for name in expected_replacements
    } == expected_replacements
    assert expected_replacements.keys() | set(expected_replacements.values()) <= set(
        contract["tools"]
    )
    assert set(contract["tools"]["get_paper"]["input_schema"]["properties"]) == {
        "document_id"
    }
    assert set(
        contract["tools"]["get_annotation_thread"]["input_schema"]["properties"]
    ) == {"thread_id"}
    assert set(
        contract["tools"]["get_research_output"]["input_schema"]["properties"]
    ) == {"item_id"}
    assert {
        "DocumentResponse",
        "ResearchItemResponse",
        "ResearchOutputList",
    } <= {
        definition
        for name in expected_replacements
        for definition in contract["tools"][name]["output_schema"].get("$defs", {})
    }
    legacy_list = contract["tools"]["list_research_outputs"]["input_schema"]
    assert legacy_list["properties"]["kinds"]["maxItems"] == 4
    assert legacy_list["$defs"]["ResearchItemKind"]["enum"] == [
        "annotation_thread",
        "citation",
        "audio_overview",
        "data_table",
    ]


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
