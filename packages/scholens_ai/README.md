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

Profile model identifiers always use `provider:model`. Server and Jobs are the
current consumers. New providers must be added as an explicit adapter rather
than silently treated as OpenAI-compatible.

The package also owns Scholens' provider-free semantic-search primitive. Image
builds download the pinned multilingual E5 ONNX artifacts once; Server and Jobs
load only a configured local artifact directory. The public document-text
builder intentionally excludes raw full text and produces a bounded,
digestible title/keywords/summary/abstract projection. Callers own
authorization, persistence, ranking, retries, and degradation behavior.

The explicit provider adapters currently cover DeepSeek (the production
default), OpenAI Chat/Responses, Google Gemini, Anthropic, AWS Bedrock, and
Moonshot. `openai:*` and `bedrock:*` identifiers are no longer rejected or
silently aliased: each uses its native Pydantic AI provider and its own
credential/region configuration. The DeepSeek adapter still uses the OpenAI
client against the fixed default `https://api.deepseek.com` endpoint.

The package is typed and ships `py.typed`. Its direct tests live in `tests/`
and run through the shared package workspace documented in
[`../README.md`](../README.md).
