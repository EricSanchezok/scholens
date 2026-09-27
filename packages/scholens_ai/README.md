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

Product DeepSeek models own their HTTP transport. Callers must enter the Agent
or Model async context for the complete operation and close streaming generators
when abandoning a response. Context exit closes connections on their owning
loop, including cancellation; profile endpoint, timeout, and retry settings
still apply. Externally supplied provider clients have a different ownership
contract and must be closed by their creator.

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

## Verbatim evidence

`evidence_segments` emits bounded 2,400-character source segments with a
400-character overlap and IDs bound to canonical content and exact bounds.
`resolve_evidence` requires a unique quote within its segment and returns the
original source slice and offsets. Reversible Unicode compatibility decomposition
and whitespace normalization are allowed; case folding, punctuation repair and
fuzzy matching are not. Unsegmented legacy results are scanned in bounded blocks
and require source-wide uniqueness. The package never persists annotations or
makes authorization decisions. Server owns personal evidence receipts and
Jobs owns prompt construction. See [ADR 0060](../../docs/decisions/0060-personal-verbatim-evidence.md).

## Shared host inference

`SCHOLENS_EMBEDDING_VARIANT` selects a registered, immutable artifact identity:
`o4` (the compatible default), `arm64-int8`, or `fp32` for evaluation. Each has
its own persisted model revision. The owner verifies both the model and
tokenizer SHA-256 before creating an ONNX session; a manifest cannot override
the registered revision. An O4 deployment without a manifest remains compatible
when its pinned file digests match. Changing variants requires matching owner
artifacts and a versioned reindex; dimensions alone do not establish compatibility.

`download_embeddings --variant arm64-int8` builds the registered dynamic
per-channel INT8 artifact from the pinned FP32 source, using MatMul and Gather
quantization. The shared workspace `model-build` group locks ONNX and NumPy;
ONNX Runtime is pinned by this package. The Server Dockerfile's separate Debian
build stage performs conversion and verifies the exact output digest before
copying only model files into the Alpine runtime. Runtime startup never
downloads or quantizes. `--tokenizer-only` supports index producers without
private model weights. Package exports are loaded on first use, preserving the
public import surface and static types. Embedding identity and dimensions live
in a lightweight contract module. The inference owner's health command uses the
same bounded socket transport and exact revision check using only the standard
library; it requires an empty, error-free health response. It does not import
NumPy, tokenizers, ONNX Runtime, validation libraries, provider clients, or an
Agent graph. Only owner startup imports model execution libraries, after
acquiring its exclusive process lock.

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
validated 384-dimensional normalized-vector response. The client splits valid
text batches by their actual serialized byte size, including UTF-8 and JSON
escapes, without truncating or reordering text. All resulting requests share one
absolute call deadline; splitting never multiplies the indexing time budget.
It serves index work in
single-text microbatches. Queries take priority between batches; after eight query
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
When several tokens share one Unicode character offset, a window retreats to
the preceding character boundary and rechecks the encoded substring. Every
retreat strictly shortens the window; the original text and complete coverage
remain unchanged. This corrects previously rejected inputs without changing
the projection format or the boundaries of already valid windows.

`scripts/benchmark_embeddings.py` compares offline variants using a labeled
synthetic bilingual engineering fixture. Provision model artifacts separately;
set `SCHOLENS_EMBEDDING_THREADS=1`, pass `--model-dir`, `--variant` and `--output`,
and run on the actual target architecture before choosing a variant. The report
includes cold start, warm query percentiles, Recall@10, NDCG@10, process peak RSS,
model/corpus digests and repeated legacy/token index measurements. This fixture
is a regression check, not a claim about production relevance or user latency.

`TokenProjection` packages exact character spans and deduplicated float32 vectors
in the checked binary format, transported as bounded base64. The result is at
most 10,000 passages with a 16 MiB binary vector bound. Canonical-source SHA-256,
model revision, finite normalized vectors, advancing spans, complete text
coverage, and the exact set of vector digests are validated before adoption.
Repeated source text can reuse a vector without collapsing distinct coordinates.

`load_passage_tokenizer` verifies the pinned tokenizer SHA before loading and
explicitly disables padding/truncation. It requires no ONNX weights or session;
tokenizer-only Jobs images can use the shared inference owner.
