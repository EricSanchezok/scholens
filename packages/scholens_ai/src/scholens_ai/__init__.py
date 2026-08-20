"""Provider-neutral AI profile and model construction primitives."""

from scholens_ai.profiles import (
    AIProfile,
    AIProfileName,
    AIThinkingEffort,
    AIThinkingMode,
    ProviderConfigurationError,
    build_model,
    profile_model_settings,
    resolve_profile,
)
from scholens_ai.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    LocalOnnxTextEmbedder,
    TextEmbedder,
    embed_text,
    semantic_document_text,
    semantic_source_digest,
    try_local_embedder,
)

__all__ = [
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
    "profile_model_settings",
    "resolve_profile",
    "semantic_document_text",
    "semantic_source_digest",
    "try_local_embedder",
]
