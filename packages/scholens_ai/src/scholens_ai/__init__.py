"""Provider-neutral AI profile and model construction primitives."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scholens_ai.embedding_contract import (
        EMBEDDING_DIMENSION as EMBEDDING_DIMENSION,
        EMBEDDING_MODEL_ID as EMBEDDING_MODEL_ID,
        EMBEDDING_MODEL_REVISION as EMBEDDING_MODEL_REVISION,
    )
    from scholens_ai.embeddings import (
        LocalOnnxTextEmbedder as LocalOnnxTextEmbedder,
        TextEmbedder as TextEmbedder,
        embed_text as embed_text,
        configured_embedder as configured_embedder,
        semantic_document_text as semantic_document_text,
        semantic_source_digest as semantic_source_digest,
        try_local_embedder as try_local_embedder,
    )
    from scholens_ai.passages import (
        MAX_PASSAGE_EMBEDDINGS as MAX_PASSAGE_EMBEDDINGS,
        MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES as MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES,
        PASSAGE_EMBEDDING_BATCH_SIZE as PASSAGE_EMBEDDING_BATCH_SIZE,
        PASSAGE_STRIDE_LINES as PASSAGE_STRIDE_LINES,
        DecodedPassageEmbeddingArtifact as DecodedPassageEmbeddingArtifact,
        DocumentPassageWindow as DocumentPassageWindow,
        PassageEmbeddingRecord as PassageEmbeddingRecord,
        build_document_passages as build_document_passages,
        decode_passage_embedding_artifact as decode_passage_embedding_artifact,
        encode_passage_embedding_artifact as encode_passage_embedding_artifact,
    )
    from scholens_ai.token_passages import (
        TOKEN_PASSAGE_REVISION as TOKEN_PASSAGE_REVISION,
        TokenPassage as TokenPassage,
        PassageLimitExceeded as PassageLimitExceeded,
        iter_token_passages as iter_token_passages,
        load_passage_tokenizer as load_passage_tokenizer,
    )
    from scholens_ai.token_projection import (
        TokenProjection as TokenProjection,
        TokenSpan as TokenSpan,
        ProjectedTokenPassage as ProjectedTokenPassage,
    )
    from scholens_ai.evidence import (
        EVIDENCE_REVISION as EVIDENCE_REVISION,
        EvidenceAnchor as EvidenceAnchor,
        EvidenceResolution as EvidenceResolution,
        EvidenceSegment as EvidenceSegment,
        evidence_segments as evidence_segments,
        resolve_evidence as resolve_evidence,
    )
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


# Keep command entrypoints independent of optional runtime stacks.
_EXPORTS = {
    name: module
    for module, names in {
        "scholens_ai.embedding_contract": (
            "EMBEDDING_DIMENSION",
            "EMBEDDING_MODEL_ID",
            "EMBEDDING_MODEL_REVISION",
        ),
        "scholens_ai.embeddings": (
            "LocalOnnxTextEmbedder",
            "TextEmbedder",
            "embed_text",
            "configured_embedder",
            "semantic_document_text",
            "semantic_source_digest",
            "try_local_embedder",
        ),
        "scholens_ai.passages": (
            "MAX_PASSAGE_EMBEDDINGS",
            "MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES",
            "PASSAGE_EMBEDDING_BATCH_SIZE",
            "PASSAGE_STRIDE_LINES",
            "DecodedPassageEmbeddingArtifact",
            "DocumentPassageWindow",
            "PassageEmbeddingRecord",
            "build_document_passages",
            "decode_passage_embedding_artifact",
            "encode_passage_embedding_artifact",
        ),
        "scholens_ai.token_passages": (
            "TOKEN_PASSAGE_REVISION",
            "TokenPassage",
            "PassageLimitExceeded",
            "iter_token_passages",
            "load_passage_tokenizer",
        ),
        "scholens_ai.token_projection": (
            "TokenProjection",
            "TokenSpan",
            "ProjectedTokenPassage",
        ),
        "scholens_ai.evidence": (
            "EVIDENCE_REVISION",
            "EvidenceAnchor",
            "EvidenceResolution",
            "EvidenceSegment",
            "evidence_segments",
            "resolve_evidence",
        ),
        "scholens_ai.profiles": (
            "AIProfile",
            "AIProfileName",
            "AIThinkingEffort",
            "AIThinkingMode",
            "ProviderConfigurationError",
            "build_model",
            "profile_model_settings",
            "resolve_profile",
        ),
    }.items()
    for name in names
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
