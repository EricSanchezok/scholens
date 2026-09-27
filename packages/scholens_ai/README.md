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
- `LocalOnnxTextEmbedder`, `TextEmbedder`, `embed_text`, `configured_embedder`
- `TokenPassage`, `iter_token_passages`, `TOKEN_PASSAGE_REVISION`
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

Passage embedding calls are bounded to eight windows per inference batch. This
limits ONNX activation memory for long, padded passages on the personal host;
the model revision, passage order, vector dimensions and artifact format stay
unchanged. The smaller batch trades processing throughput for bounded memory.

The explicit provider adapters currently cover DeepSeek (the production
default), OpenAI Chat/Responses, Google Gemini, Anthropic, AWS Bedrock, and
Moonshot. `openai:*` and `bedrock:*` identifiers are no longer rejected or
silently aliased: each uses its native Pydantic AI provider and its own
credential/region configuration. The DeepSeek adapter still uses the OpenAI
client against the fixed default `https://api.deepseek.com` endpoint.

The package is typed and ships `py.typed`. Its direct tests live in `tests/`
and run through the shared package workspace documented in
[`../README.md`](../README.md).

`build_model(..., api_key=...)` accepts an explicit nonempty user key only for
DeepSeek profiles and pins the official DeepSeek endpoint. Server and Jobs own
credential lookup and supply this argument for product workloads. Omitting it
retains the package's environment-provider API for non-product tools/tests; it
is never the product fallback path.

`SCHOLENS_EMBEDDING_THREADS` optionally bounds local ONNX intra-op threads (1–32)
and sets inter-op threads to one. Unset retains ONNX defaults. Personal document
workers set one; Server behavior is unchanged. This execution setting changes no
model revision, dimensions, normalized-vector contract or stored artifact format.

## Shared host inference

`SCHOLENS_EMBEDDING_SOCKET` selects a private Unix socket client for both Server
and Jobs. Failure, overload or deadline expiry never falls back to loading a
second model. Without this setting, explicitly provisioned local environments
retain local model support. Run the owner with
`python -m scholens_ai.inference --socket /run/scholens-inference/model.sock`;
`--check` verifies readiness and exact model revision. The socket directory must
be private to the participating containers and writable by the owner. An
exclusive process lock is acquired before loading weights; the socket has mode
`0660`. No TCP listener or provider credential is involved.

The owner has one inference thread, at most 64 connections and queued requests,
256 KiB frames, eight texts of at most 24,000 characters per request, and a
validated 384-dimensional normalized-vector response. It serves index work in
two-text microbatches. Queries take priority between batches; after eight query
batches one waiting index batch can run. Client deadlines are 750 ms for queries
and 30 seconds for indexing. Disconnection cancels queued work. Low-cardinality
JSON logs include kind, revision, duration, count, queue depth and status, never
query text or vectors. Production resource bounds must be set from measured
native-host peaks, not model file size.

Server prepares query vectors before opening search transactions and preserves
lexical search when inference is unavailable. Vectors carry the query digest and
model revision; mismatches never join stored semantic projections.

`iter_token_passages` is an additive projection primitive, not a silent change to
legacy five-line indexing. It yields paragraph-aware windows of at most 256
tokens with 32-token overlap and unchanged canonical character/line coordinates.
An 8,192-character rolling lookahead bounds tokenizer memory. The caller supplies
the pinned tokenizer with padding and truncation disabled. Exceeding 10,000
passages raises explicitly, leaving adoption of a partial index to the caller;
old searchable content must not be replaced by a silently truncated projection.

`scripts/benchmark_embeddings.py` compares offline variants using a labeled
synthetic bilingual engineering fixture. Provision model artifacts separately;
set `SCHOLENS_EMBEDDING_THREADS=1`, pass `--model-dir`, `--variant` and `--output`,
and run on the actual target architecture before choosing a variant. The report
includes cold start, warm query percentiles, Recall@10, NDCG@10, process peak RSS,
model/corpus digests and repeated legacy/token index measurements. This fixture
is a regression check, not a claim about production relevance or user latency.
