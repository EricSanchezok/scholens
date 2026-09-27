"""Provider-neutral AI profile and model construction primitives."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scholens_ai.profiles import (
        AIProfile as AIProfile,
        AIProfileName as AIProfileName,
        AIThinkingEffort as AIThinkingEffort,
        AIThinkingMode as AIThinkingMode,
        ProviderConfigurationError as ProviderConfigurationError,
        build_model as build_model,
        profile_model_settings as profile_model_settings,
        resolve_profile as resolve_profile,
    )

from scholens_ai.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    LocalOnnxTextEmbedder,
    TextEmbedder,
    embed_text,
    configured_embedder,
    semantic_document_text,
    semantic_source_digest,
    try_local_embedder,
)
from scholens_ai.passages import (
    MAX_PASSAGE_EMBEDDINGS,
    MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES,
    PASSAGE_EMBEDDING_BATCH_SIZE,
    PASSAGE_STRIDE_LINES,
    DecodedPassageEmbeddingArtifact,
    DocumentPassageWindow,
    PassageEmbeddingRecord,
    build_document_passages,
    decode_passage_embedding_artifact,
    encode_passage_embedding_artifact,
)

from scholens_ai.token_passages import (
    TOKEN_PASSAGE_REVISION,
    TokenPassage,
    PassageLimitExceeded,
    iter_token_passages,
)
from scholens_ai.evidence import (
    EVIDENCE_REVISION,
    EvidenceAnchor,
    EvidenceResolution,
    EvidenceSegment,
    evidence_segments,
    resolve_evidence,
)

__all__ = [
    "EVIDENCE_REVISION",
    "EvidenceAnchor",
    "EvidenceResolution",
    "EvidenceSegment",
    "evidence_segments",
    "resolve_evidence",
    "TOKEN_PASSAGE_REVISION",
    "TokenPassage",
    "PassageLimitExceeded",
    "iter_token_passages",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_REVISION",
    "AIProfile",
    "AIProfileName",
    "AIThinkingEffort",
    "AIThinkingMode",
    "ProviderConfigurationError",
    "LocalOnnxTextEmbedder",
    "TextEmbedder",
    "build_model",
    "embed_text",
    "configured_embedder",
    "profile_model_settings",
    "resolve_profile",
    "semantic_document_text",
    "semantic_source_digest",
    "try_local_embedder",
    "MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES",
    "MAX_PASSAGE_EMBEDDINGS",
    "PASSAGE_EMBEDDING_BATCH_SIZE",
    "PASSAGE_STRIDE_LINES",
    "DecodedPassageEmbeddingArtifact",
    "DocumentPassageWindow",
    "PassageEmbeddingRecord",
    "build_document_passages",
    "decode_passage_embedding_artifact",
    "encode_passage_embedding_artifact",
]


_PROFILE_EXPORTS = frozenset(
    {
        "AIProfile",
        "AIProfileName",
        "AIThinkingEffort",
        "AIThinkingMode",
        "ProviderConfigurationError",
        "build_model",
        "profile_model_settings",
        "resolve_profile",
    }
)


def __getattr__(name: str) -> Any:
    # The inference owner needs no provider SDKs, credentials or Agent graph.
    # Keep the public import API while loading model providers only on use.
    if name not in _PROFILE_EXPORTS:
        raise AttributeError(name)
    from scholens_ai import profiles

    value = getattr(profiles, name)
    globals()[name] = value
    return value
