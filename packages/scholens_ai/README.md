# scholens-ai

`scholens-ai` is the provider-neutral AI configuration boundary shared by
Server and Jobs. It owns named workload profiles, validated environment
configuration, deterministic profile revisions, provider selection, and model
settings. It does not own prompts, product workflows, authorization, provider
credentials, or retry orchestration outside model construction.

## Public contract

Import the supported surface from `scholens_ai`:

- `AIProfile`, `AIProfileName`
- `AIThinkingMode`, `AIThinkingEffort`
- `ProviderConfigurationError`
- `resolve_profile`, `profile_model_settings`, `build_model`
- `LocalOnnxTextEmbedder`, `TextEmbedder`, `embed_text`
- `semantic_document_text`, `semantic_source_digest`
- `EMBEDDING_MODEL_REVISION`, `EMBEDDING_DIMENSION`
- `build_document_passages`, `DocumentPassageWindow`
- `PassageEmbeddingRecord`, `encode_passage_embedding_artifact`,
  `decode_passage_embedding_artifact`

Profile model identifiers always use `provider:model`. Server and Jobs are the
current consumers. New providers must be added as an explicit adapter rather
than silently treated as OpenAI-compatible.

The package also owns Scholens' provider-free semantic-search primitive. Image
builds download the pinned multilingual E5 ONNX artifacts once; Server and Jobs
load only a configured local artifact directory. The public document-text
builder intentionally excludes raw full text and produces a bounded,
digestible title/keywords/summary/abstract projection. Callers own
authorization, persistence, ranking, retries, and degradation behavior.

The package also defines the canonical five-line, three-line-stride passage
window and a fixed binary interchange format used between Jobs and Server. The
codec accepts only the pinned 384-dimensional normalized vectors, SHA-256
content digests, a bounded model revision, at most 10,000 records, and at most
16 MiB. It is data-only—not a pickle or executable serialization. Callers still
own artifact storage authorization, checksums, lifecycle, transactions, and
matching a digest back to current canonical content.

The explicit provider adapters currently cover DeepSeek (the production
default), OpenAI Chat/Responses, Google Gemini, Anthropic, AWS Bedrock, and
Moonshot. `openai:*` and `bedrock:*` identifiers are no longer rejected or
silently aliased: each uses its native Pydantic AI provider and its own
credential/region configuration. The DeepSeek adapter still uses the OpenAI
client against the fixed default `https://api.deepseek.com` endpoint.

The package is typed and ships `py.typed`. Its direct tests live in `tests/`
and run through the shared package workspace documented in
[`../README.md`](../README.md).
