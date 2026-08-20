"""Download the pinned search model files during an image build."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download

EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"

FILES = (
    "onnx/model_O4.onnx",
    "onnx/tokenizer.json",
    "onnx/tokenizer_config.json",
    "onnx/special_tokens_map.json",
    "onnx/sentencepiece.bpe.model",
)


def download_model(target: Path, *, revision: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for filename in FILES:
        source = Path(
            hf_hub_download(
                repo_id=EMBEDDING_MODEL_ID,
                filename=filename,
                revision=revision,
            )
        )
        destination_name = (
            "model.onnx" if filename.endswith("model_O4.onnx") else source.name
        )
        shutil.copyfile(source, target / destination_name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    download_model(args.target, revision=args.revision)


if __name__ == "__main__":
    main()
