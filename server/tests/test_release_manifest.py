from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_manifest",
    ROOT / "scripts/release_manifest.py",
)
assert SPEC is not None and SPEC.loader is not None
release_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_manifest)


def _source_map_index(path: Path, *, release_sha: str = "b" * 40) -> Path:
    relative = "static/chunks/app.js.map"
    checksum = "c" * 64
    size = 128
    aggregate = hashlib.sha256()
    aggregate.update(relative.encode())
    aggregate.update(b"\0")
    aggregate.update(checksum.encode())
    aggregate.update(b"\0")
    aggregate.update(str(size).encode())
    aggregate.update(b"\n")
    path.write_text(
        json.dumps(
            {
                "aggregate_sha256": aggregate.hexdigest(),
                "contract_version": 1,
                "files": [
                    {"path": relative, "sha256": checksum, "size": size},
                ],
                "release_sha": release_sha,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _arguments(tmp_path: Path) -> argparse.Namespace:
    digest = "a" * 64
    registry = "919651863140.dkr.ecr.ap-southeast-1.amazonaws.com"
    scans = {
        component: {
            "digest": f"sha256:{digest}",
            "scan_digest": f"sha256:{digest}",
            "platform": "linux/amd64",
            "status": "COMPLETE",
            "completed_at": "2026-08-16T12:10:00Z",
            "findings": {"CRITICAL": 0, "HIGH": 0},
        }
        for component in release_manifest.IMAGE_COMPONENTS
    }
    return argparse.Namespace(
        release_sha="b" * 40,
        created_at="2026-08-16T12:00:00Z",
        identity_schema_version=1,
        web_api_url="https://scholens.sanchezcloud.net",
        account_center_url="https://myaccount.sanchezcloud.net",
        web_image=f"{registry}/sanchezcloud-scholens-web@sha256:{digest}",
        api_image=f"{registry}/sanchezcloud-scholens-api@sha256:{digest}",
        jobs_image=f"{registry}/sanchezcloud-scholens-jobs@sha256:{digest}",
        source_maps_index=_source_map_index(tmp_path / "index.json"),
        image_scans_contract=scans,
    )


def test_release_manifest_is_deterministic_and_source_bound(tmp_path: Path) -> None:
    first = release_manifest.create_manifest(_arguments(tmp_path))
    second = release_manifest.create_manifest(_arguments(tmp_path))

    assert first == second
    assert first["release_sha"] == "b" * 40
    assert first["runtime_template_sha256"]
    assert first["public_openapi_sha256"]
    release_manifest.verify_manifest(
        first,
        "b" * 40,
        expected_account_id="919651863140",
        expected_region="ap-southeast-1",
    )
    assert first["source_maps"]["file_count"] == 1
    assert first["source_maps"]["index_key"].startswith(f"source-maps/{'b' * 40}/")
    assert first["source_maps"]["index_key"].endswith("/index.json")


def test_release_manifest_rejects_mutable_image_tags(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    arguments.web_image = "registry.example/scholens-web:latest"

    with pytest.raises(ValueError, match="digest-qualified web image"):
        release_manifest.create_manifest(arguments)


def test_release_manifest_rejects_cross_account_or_region_image(
    tmp_path: Path,
) -> None:
    manifest = release_manifest.create_manifest(_arguments(tmp_path))

    with pytest.raises(ValueError, match="expected AWS registry"):
        release_manifest.verify_manifest(
            manifest,
            "b" * 40,
            expected_account_id="000000000000",
            expected_region="ap-southeast-1",
        )
    with pytest.raises(ValueError, match="expected AWS registry"):
        release_manifest.verify_manifest(
            manifest,
            "b" * 40,
            expected_account_id="919651863140",
            expected_region="us-east-1",
        )


def test_release_manifest_rejects_scan_for_another_digest(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    arguments.image_scans_contract["api"]["digest"] = f"sha256:{'d' * 64}"

    with pytest.raises(ValueError, match="scan does not match its digest"):
        release_manifest.create_manifest(arguments)


def test_identity_reference_must_match_lock_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "pyproject.toml").write_text(
        '[project]\ndependencies = ["sanchezcloud-identity @ '
        'git+https://github.com/EricSanchezok/sanchezcloud-identity.git@v2"]\n',
        encoding="utf-8",
    )
    (server / "uv.lock").write_text(
        'source = { git = "https://github.com/EricSanchezok/'
        f'sanchezcloud-identity.git?rev=v1#{"a" * 40}" }}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(release_manifest, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="does not match pyproject"):
        release_manifest._identity_resolution()


def test_migration_attestation_is_deterministic_and_manifest_bound(
    tmp_path: Path,
) -> None:
    manifest = release_manifest.create_manifest(_arguments(tmp_path))

    first = release_manifest.migration_attestation(manifest)
    second = release_manifest.migration_attestation(manifest)

    assert first == second
    assert first["release_sha"] == manifest["release_sha"]
    assert first["scholens_migrations"] == manifest["scholens_migrations"]
    assert first["identity"] == manifest["identity"]
    release_manifest.verify_migration_attestation(first, manifest)

    altered = json.loads(json.dumps(first))
    altered["scholens_migrations"]["head"] = "wrong-head"
    with pytest.raises(ValueError, match="does not match"):
        release_manifest.verify_migration_attestation(altered, manifest)

    old_identity = json.loads(json.dumps(first["database_runtime_proof"]))
    old_identity["identity"]["installed_schema_version"] -= 1
    with pytest.raises(ValueError, match="runtime migration proof"):
        release_manifest.migration_attestation(manifest, old_identity)


def test_old_attestation_cannot_authorize_release_after_database_advances(
    tmp_path: Path,
) -> None:
    manifest = release_manifest.create_manifest(_arguments(tmp_path))
    attestation = release_manifest.migration_attestation(manifest)
    current = json.loads(json.dumps(attestation))
    current["release_sha"] = "d" * 40
    current["release_manifest_sha256"] = "e" * 64
    current["scholens_migrations"]["head"] = "new-incompatible-head"

    with pytest.raises(ValueError, match="current database migration contract"):
        release_manifest.verify_database_contract(attestation, current, manifest)


def test_migration_head_comes_from_graph_not_lexical_filename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = tmp_path / "server" / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "z_root.py").write_text(
        'revision = "root"\ndown_revision = None\n',
        encoding="utf-8",
    )
    (versions / "a_actual_head.py").write_text(
        'revision = "actual-head"\ndown_revision = "root"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(release_manifest, "ROOT", tmp_path)

    assert release_manifest._migration_contract()["head"] == "actual-head"


def test_migration_contract_rejects_multiple_heads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = tmp_path / "server" / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "root.py").write_text(
        'revision = "root"\ndown_revision = None\n',
        encoding="utf-8",
    )
    (versions / "head_one.py").write_text(
        'revision = "head-one"\ndown_revision = "root"\n',
        encoding="utf-8",
    )
    (versions / "head_two.py").write_text(
        'revision = "head-two"\ndown_revision = "root"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(release_manifest, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="exactly one head"):
        release_manifest._migration_contract()


def test_template_parameters_are_read_as_data_from_an_old_release(
    tmp_path: Path,
) -> None:
    template = tmp_path / "production.yml"
    template.write_text(
        "AWSTemplateFormatVersion: '2010-09-09'\n"
        "Parameters:\n"
        "  ReleaseSha: {Type: String}\n"
        "  ApplicationEnabled:\n"
        "    Type: String\n"
        "Conditions: {}\n",
        encoding="utf-8",
    )

    assert release_manifest._template_parameter_names(template) == (
        "ReleaseSha",
        "ApplicationEnabled",
    )
