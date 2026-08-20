"""Local, deterministic multilingual embeddings shared by Server and Jobs."""

from __future__ import annotations

import hashlib
import os
from functools import cached_property, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, Sequence

import numpy as np
from tokenizers import Tokenizer

if TYPE_CHECKING:
    import onnxruntime as ort  # type: ignore[import-untyped]

EMBEDDING_DIMENSION = 384
EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"
EMBEDDING_MODEL_REVISION = "multilingual-e5-small-onnx-o4-v1"
EMBEDDING_MAX_TOKENS = 512


class TextEmbedder(Protocol):
    """Minimal embedding boundary used by search infrastructure."""

    @property
    def revision(self) -> str: ...

    def embed_query(self, text: str) -> list[float]: ...

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...


def semantic_document_text(
    *,
    title: str | None,
    keywords: Sequence[str] | None,
    summary: str | None,
    abstract: str | None,
) -> str:
    """Build the bounded, stable v1 semantic projection in priority order."""
    sections = [
        title or "",
        " · ".join(keywords or ()),
        summary or "",
        abstract or "",
    ]
    return "\n\n".join(section.strip() for section in sections if section.strip())[
        :24_000
    ]


def semantic_source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LocalOnnxTextEmbedder:
    """Run multilingual E5 locally; never sends query or paper text over a network."""

    def __init__(self, model_dir: str | Path | None = None) -> None:
        configured = model_dir or os.getenv("SCHOLENS_EMBEDDING_MODEL_PATH")
        if not configured:
            raise RuntimeError("SCHOLENS_EMBEDDING_MODEL_PATH is not configured")
        self._model_dir = Path(configured)
        self._tokenizer_path = self._model_dir / "tokenizer.json"
        self._model_path = self._model_dir / "model.onnx"
        if not self._tokenizer_path.is_file() or not self._model_path.is_file():
            raise RuntimeError("local embedding model artifacts are incomplete")

    @property
    def revision(self) -> str:
        return EMBEDDING_MODEL_REVISION

    @cached_property
    def _tokenizer(self) -> Tokenizer:
        tokenizer = Tokenizer.from_file(str(self._tokenizer_path))
        tokenizer.enable_truncation(max_length=EMBEDDING_MAX_TOKENS)
        pad_id = tokenizer.token_to_id("<pad>")
        tokenizer.enable_padding(
            pad_id=pad_id if pad_id is not None else 1,
            pad_token="<pad>",
        )
        return tokenizer

    @cached_property
    def _session(self) -> ort.InferenceSession:
        # Keep the runtime import lazy so image-build utilities can download the
        # pinned artifacts before the runtime-specific ONNX package is present.
        import onnxruntime as ort

        return ort.InferenceSession(
            str(self._model_path), providers=["CPUExecutionProvider"]
        )

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"query: {text.strip()}"])[0]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([f"passage: {text.strip()}" for text in texts])

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding input must contain non-empty text")
        encodings = self._tokenizer.encode_batch(list(texts))
        input_ids = np.asarray([encoding.ids for encoding in encodings], dtype=np.int64)
        attention_mask = np.asarray(
            [encoding.attention_mask for encoding in encodings], dtype=np.int64
        )
        session_inputs: dict[str, np.ndarray] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        input_names = {item.name for item in self._session.get_inputs()}
        if "token_type_ids" in input_names:
            session_inputs["token_type_ids"] = np.asarray(
                [encoding.type_ids for encoding in encodings], dtype=np.int64
            )
        hidden_state = np.asarray(
            self._session.run(None, session_inputs)[0], dtype=np.float32
        )
        mask = attention_mask[..., None].astype(np.float32)
        pooled = (hidden_state * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.maximum(norms, 1e-12)
        if normalized.shape[1] != EMBEDDING_DIMENSION:
            raise RuntimeError("embedding model returned an unexpected dimension")
        return [[float(value) for value in row] for row in normalized]


@lru_cache(maxsize=1)
def try_local_embedder() -> LocalOnnxTextEmbedder | None:
    try:
        return LocalOnnxTextEmbedder()
    except RuntimeError:
        return None


def embed_text(
    text: str,
    *,
    kind: Literal["query", "passage"],
    embedder: TextEmbedder | None = None,
) -> list[float] | None:
    selected = embedder or try_local_embedder()
    if selected is None:
        return None
    if kind == "query":
        return selected.embed_query(text)
    return selected.embed_passages([text])[0]
