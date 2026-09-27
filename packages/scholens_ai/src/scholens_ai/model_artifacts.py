"""Pinned artifact identities, independent of file paths and vector dimensions."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

SOURCE_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
TOKENIZER_SHA256 = "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"
FP32_SHA256 = "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665"


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    variant: str
    revision: str
    model_sha256: str
    tokenizer_sha256: str = TOKENIZER_SHA256


MODEL_ARTIFACTS = {
    "o4": ModelArtifact(
        "o4",
        "multilingual-e5-small-onnx-o4-v1",
        "4654c156f3e4171abc9c716cdb771bf9116455d15ac1aab364aeeede0e3205b0",
    ),
    "arm64-int8": ModelArtifact(
        "arm64-int8",
        "multilingual-e5-small-onnx-arm64-int8-v1",
        "739c8f25bbe6d8a6001cd2f048701da9879140cc67d4e9327716111e869dd717",
    ),
    "fp32": ModelArtifact("fp32", "multilingual-e5-small-onnx-fp32-v1", FP32_SHA256),
}


def model_artifact(variant: str | None = None) -> ModelArtifact:
    name = variant or os.getenv("SCHOLENS_EMBEDDING_VARIANT") or "o4"
    try:
        return MODEL_ARTIFACTS[name]
    except KeyError as exc:
        raise ValueError("Unknown embedding model variant") from exc


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify_artifacts(directory: Path, expected: ModelArtifact) -> None:
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        if manifest_path.stat().st_size > 4096:
            raise ValueError("Invalid embedding artifact manifest")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("model_revision") != expected.revision:
            raise ValueError("Embedding artifact revision mismatch")
    for name, digest in (
        ("model.onnx", expected.model_sha256),
        ("tokenizer.json", expected.tokenizer_sha256),
    ):
        if file_sha256(directory / name) != digest:
            raise ValueError("Embedding artifact digest mismatch")


__all__ = ["SOURCE_REVISION", "ModelArtifact", "model_artifact", "verify_artifacts"]
