import hashlib
import json
import subprocess
import sys

import pytest

from scholens_ai.model_artifacts import ModelArtifact, model_artifact, verify_artifacts


def test_variants_have_distinct_persistence_identities_and_unknown_is_rejected():
    legacy, quantized = model_artifact("o4"), model_artifact("arm64-int8")
    assert legacy.revision == "multilingual-e5-small-onnx-o4-v1"
    assert legacy.revision != quantized.revision
    assert legacy.model_sha256 != quantized.model_sha256
    with pytest.raises(ValueError, match="variant"):
        model_artifact("automatic")


def fixture(tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"model")
    (tmp_path / "tokenizer.json").write_bytes(b"tokenizer")
    return ModelArtifact(
        "fixture",
        "test-v1",
        hashlib.sha256(b"model").hexdigest(),
        hashlib.sha256(b"tokenizer").hexdigest(),
    )


def test_pinned_legacy_files_without_manifest_remain_compatible(tmp_path):
    verify_artifacts(tmp_path, fixture(tmp_path))


@pytest.mark.parametrize("name", ["model.onnx", "tokenizer.json"])
def test_mutated_artifact_never_claims_the_expected_revision(tmp_path, name):
    spec = fixture(tmp_path)
    (tmp_path / name).write_bytes(b"modified")
    with pytest.raises(ValueError, match="digest"):
        verify_artifacts(tmp_path, spec)


def test_artifact_manifest_cannot_override_the_configured_revision(tmp_path):
    spec = fixture(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"model_revision": "different"}))
    with pytest.raises(ValueError, match="revision"):
        verify_artifacts(tmp_path, spec)


def test_inference_owner_does_not_import_provider_sdks():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import scholens_ai.inference; "
            "assert not any(n.startswith(('pydantic_ai', 'openai', 'anthropic', 'google.genai')) for n in sys.modules)",
        ],
        check=True,
    )
