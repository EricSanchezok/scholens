"""Download the pinned search model files during an image build."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download
from scholens_ai.model_artifacts import (
    FP32_SHA256,
    SOURCE_REVISION,
    file_sha256,
    model_artifact,
    verify_artifacts,
)

EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"

FILES = (
    "onnx/tokenizer.json",
    "onnx/tokenizer_config.json",
    "onnx/special_tokens_map.json",
    "onnx/sentencepiece.bpe.model",
)


def download_model(
    target: Path, *, revision: str, variant: str = "o4", tokenizer_only: bool = False
) -> None:
    if not revision.strip():
        raise ValueError("embedding model revision must not be empty")
    if revision != SOURCE_REVISION:
        raise ValueError("embedding source revision is not registered")
    artifact = model_artifact(variant)

    target.mkdir(parents=True, exist_ok=True)
    for filename in FILES:
        source = Path(
            hf_hub_download(
                repo_id=EMBEDDING_MODEL_ID,
                filename=filename,
                revision=revision,
            )
        )
        shutil.copyfile(source, target / source.name)
    if file_sha256(target / "tokenizer.json") != artifact.tokenizer_sha256:
        raise ValueError("Tokenizer artifact digest mismatch")
    if tokenizer_only:
        return
    source = Path(
        hf_hub_download(
            repo_id=EMBEDDING_MODEL_ID,
            filename="onnx/model_O4.onnx" if variant == "o4" else "onnx/model.onnx",
            revision=revision,
        )
    )
    if variant == "arm64-int8":
        if file_sha256(source) != FP32_SHA256:
            raise ValueError("FP32 source artifact digest mismatch")
        _quantize(source, target / "model.onnx")
    else:
        shutil.copyfile(source, target / "model.onnx")
    verify_artifacts(target, artifact)
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "model_revision": artifact.revision,
                "variant": artifact.variant,
                "source_revision": SOURCE_REVISION,
                "model_sha256": artifact.model_sha256,
                "tokenizer_sha256": artifact.tokenizer_sha256,
            },
            sort_keys=True,
        )
        + "\n"
    )


def _quantize(source: Path, target: Path) -> None:
    # Build-only dependencies are pinned in the shared workspace model-build
    # group. Runtime containers never quantize or download model artifacts.
    from onnxruntime.quantization import QuantType, quantize_dynamic  # type: ignore[import-untyped]

    quantize_dynamic(
        str(source),
        str(target),
        weight_type=QuantType.QInt8,
        per_channel=True,
        reduce_range=False,
        op_types_to_quantize=["MatMul", "Gather"],
        extra_options={"WeightSymmetric": True, "MatMulConstBOnly": True},
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--variant", choices=("o4", "fp32", "arm64-int8"), default="o4")
    parser.add_argument("--tokenizer-only", action="store_true")
    args = parser.parse_args()
    download_model(
        args.target,
        revision=args.revision,
        variant=args.variant,
        tokenizer_only=args.tokenizer_only,
    )


if __name__ == "__main__":
    main()
