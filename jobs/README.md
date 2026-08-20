# Scholens Jobs

The Jobs service runs long-lived Scholens workflows outside the API process.
Celery workers consume local RabbitMQ or production SQS queues, use Redis only
for shared limits and resumable parser state, and return signed results to the
Server webhook API. Celery has no result backend; PostgreSQL-owned jobs and
signed callbacks are the durable state contract.

## PDF ingestion

The PDF worker follows one explicit, local-first pipeline:

1. Download the original PDF from private S3 storage.
2. Analyze the PDF locally with PyMuPDF: per-page text statistics, preview,
   and deterministic page offsets (milliseconds per page).
3. Classify the document:
   - **Scanned PDF** (empty or near-empty text layer, or repeated boilerplate
     such as per-page watermarks) is submitted to MinerU, the only OCR-capable
     parser, and shares one 600-second deadline across polling and archive
     download.
   - **Digital PDF** (≥80% of uploads: arXiv, journal, most conference PDFs)
     stays local:
     a. `pymupdf4llm` extracts page-chunked Markdown with exact per-page
     offsets (primary engine);
     b. on failure, `markitdown` is tried as a second engine and is persisted
     as `text_only` because its output has no page boundaries (offsets are
     approximated from the local page analysis);
     c. if both local engines fail, MinerU rescues the document (OCR can
     recover misclassified or malformed PDFs);
     d. if the MinerU rescue fails or times out, the deterministic per-page
     text from step 2 is persisted as `text_only` with exact offsets.
4. Store Markdown and preview; only the MinerU path produces an audit archive
   (`mineru-result.zip`).
5. Extract metadata with DeepSeek unless the caller supplied authoritative
   metadata, as Zotero imports do.
6. Build the bounded title/keywords/summary/abstract semantic projection with
   the pinned local multilingual embedding model. Embedding failure is
   non-fatal and leaves lexical search available.
7. Send the result, optional versioned embedding, and token usage to Server
   through an HMAC-signed webhook.

The worker also sends a signed stage projection and heartbeat at bounded
intervals. Public progress is limited to `queued`, `parsing`, `extracting`,
`indexing`, and `finalizing`; provider-specific payloads never become client
state. The task checks Server-owned cancellation before and after expensive
boundaries. Revocation uses `terminate=False`: pending work can be skipped, and
running work exits cooperatively without killing a worker process. Soft and hard
task limits bound the complete workflow so a lost provider response cannot
leave a Library row processing forever.

The production image stores the pinned search model at
`SCHOLENS_EMBEDDING_MODEL_PATH`. It never downloads a model at task execution
time and never sends the semantic projection to a remote provider.

Local engines (`pymupdf4llm`, `markitdown`) are CPU-only, run in-process with
a bounded time budget per engine, and never send document content off-host.
MinerU is used only for scanned PDFs and as a rescue for digital PDFs whose
local extraction failed; its results are persisted as `full` quality. A
`text_only` result (local fallback or rescue timeout) is persisted so the
client can warn that layout-dependent content may be incomplete.

MinerU task IDs are checkpointed in Redis under a digest of the job ID, job
purpose, document content hash, and credential revision, so two jobs parsing
the same PDF never reuse each other's provider batch or archive. Four
consecutive network failures switch polling or downloading to a slower bounded
backoff; they do not end the task before its deadline. Redelivery and later
retry attempts with the same job, source, and credential resume the same
provider task instead of submitting another one. A retryable failure retains
the checkpoint; successful and non-retryable provider outcomes clear it once
the provider result no longer needs to be resumed.

## AI reading reflow

AI reflow starts only when the user explicitly requests an attempt and has an
enabled MinerU connection. Server dispatches `generate_document_reflow` to the
`document` queue with an internal, job-scoped credential URL—not the token. After
claiming the job, the worker fetches the current revision-scoped credential,
downloads the original PDF, and submits it to MinerU. Reflow consumes the stable
`content_list.json` from the returned archive instead of flattening Markdown and
asking a language model to rediscover structure. MinerU's reading order, block
types, page indices, normalized rectangles, tables, equations, lists, and image
paths become a continuous academic Markdown AST.

Deterministic normalization removes unsafe HTML residue, converts supported
superscript/subscript markup, joins parser-only line wrapping, and filters page
chrome. Every rendered block retains one or more source spans with the original
item index, page, rectangle, and text. Missing visual assets or unsupported
items degrade only that block to a PDF fallback; there is no reflow-specific
LLM profile and no whole-document rewrite. Stable block and asset IDs, safe
render Markdown, source spans, presentation status, source fingerprint, parser
revision, and warnings return through the signed callback. Server remains the
persistence authority.

## Zotero import and synchronization

Zotero work is read-only and begins only from a Server-owned DurableJob. The
task payload contains owner, operation, requested Zotero item keys, signed
credential/progress/callback URLs, and non-secret policy. After claiming the
job, the worker retrieves the current API key and Zotero user ID from the
signed, job-scoped Server endpoint. It never persists that key or includes it
in Celery payloads, callbacks, logs, exceptions, or telemetry.

An import fetches supported personal-library items, resolves a stored PDF or a
bounded trustworthy source, validates the download as a safe PDF, uploads it to
temporary private S3 storage, and reports each result independently. Server
then creates the ordinary paper-ingestion lifecycle with Zotero metadata as
the authority. One bad item therefore yields a partial operation instead of
rolling back accepted papers. Provider rate limits use bounded retry delay;
credential replacement, disconnect, and cancellation are checked at expensive
boundaries. Every Zotero provider session ignores environment proxies and has an
explicit context-managed close on success and failure; public PDF
redirects are revalidated against the connected peer address, and a Zotero API
key is never forwarded across origins. Controlled provider failures and
cooperative cancellation before callback delivery remove temporary
`zotero-imports/` objects. An HTTP timeout, connection loss, or 5xx after
delivery begins has an unknown Server outcome, so Jobs must retain those
objects; Server removes them after definite completion, while the bucket's
two-day lifecycle is the crash and ambiguous-delivery fallback.
Worker inputs and provider outputs must use canonical eight-character Zotero
item, attachment, collection, and annotation keys. Metadata and annotation
snapshots are bounded before callback delivery so a provider-controlled library
cannot amplify an internal callback without limit.

Jobs enforces the shared 12 MiB callback ceiling while it builds a result, not
only immediately before HTTP delivery. Manual import retains one small stable
`zotero_callback_budget_exceeded` result for every requested key it cannot fit,
stops further provider reads, and deletes any just-prepared staging object that
was not admitted to the callback. Sync reads annotation targets only until its
bounded projection is full, leaving later targets absent so Server does not
advance their attempt time and they remain first in the next fair scheduling
window. When automatic import is active, 4 MiB is reserved from the annotation
projection for that work. Automatic items are admitted one at a time; a first
item that does not fit is deleted from staging, the provider page is left
uncaught-up, and Server can advance only through the prefix actually returned.
The exact compact UTF-8 JSON body is checked again before signing and sending.

The shared completion contract gives Server a 12-minute processing bound,
Jobs a 13-minute HTTP timeout, and the Server claim a renewable 15-minute
lease with a 30-second heartbeat. This ordering lets a healthy Server return a
stable timeout before Jobs abandons the request, while an active callback
cannot be recovered by a second replica. Jobs never deletes staging merely
because its own HTTP wait elapsed.

A sync fetches new annotations for papers already imported into Scholens and
returns their Zotero annotation keys for idempotent append-only application.
Automatic Researcher runs may additionally request items modified after the
Server-provided library-version checkpoint. Each run reads at most 50 later
items from a stable ascending provider page and returns both its bounded page
position and the observed final version. Server alone advances the recoverable
checkpoint through the contiguous success/permanent-skip prefix; transient or
quota failures remain eligible on the next run. The worker does not infer
eligibility, enable auto import, or own the checkpoint. Group
Libraries, annotation deletion/overwrite, and writes to Zotero are outside the
worker contract.
Annotation-target failures retain their stable error code. Missing attachment
responses are distinguished from transient failures so Server can stop polling
an unavailable source without pretending that annotations synchronized.

## Code layout

```text
src/
├── pdf/
│   ├── models.py    # Parse results and classified errors
│   ├── mineru.py    # MinerU lifecycle, archive security, normalization
│   ├── local.py     # PyMuPDF analysis and fallback
│   ├── state.py     # Redis task checkpoint and submit lock
│   └── pipeline.py  # Parser selection, S3 artifacts, metadata
├── tasks.py         # Thin Celery task adapters
├── zotero.py        # Read-only Zotero import, PDF validation, and incremental sync
├── reflow.py        # MinerU content-list normalization and continuous AST
├── llm_client.py    # provider-neutral structured AI client
├── s3_service.py
└── webhook_signing.py
```

Parser-specific tests mirror this structure under `tests/pdf/`.

## Configuration

The repository-level [`.env.example`](../.env.example) is the only environment
variable catalog. Copy the values needed by Jobs into `jobs/.env`; never commit
that file.

Production requires:

- SQS through `CELERY_BROKER_URL=sqs://` and the three predefined
  `SQS_DOCUMENT_QUEUE_URL`, `SQS_RESEARCH_QUEUE_URL`, and
  `SQS_MAINTENANCE_QUEUE_URL` values. The shared contract also defines
  `conversation`, but that queue is owned and consumed only by the Server-image
  Conversation worker; Jobs must never subscribe to it.
- the shared cache through strict `CACHE_HOST`, `CACHE_PORT`, `CACHE_USERNAME`,
  `CACHE_PASSWORD`, and `CACHE_TLS=true` fields
- S3 credentials and bucket names
- non-secret MinerU runtime policy (`MINERU_API_BASE_URL`, timeouts, and limits)
- the `SCHOLENS_AI_*` profile variables and the selected provider credential
- `JOBS_WEBHOOK_SIGNING_SECRET`

MinerU tokens are user-owned connections stored by Server, never Jobs process
environment. Jobs fetches a token only after claiming an eligible PDF or
document-reflow job through the signed, job-scoped internal callback surface.
Production fails fast unless the composed cache endpoint is authenticated
`rediss://` on an ElastiCache hostname and all non-secret runtime configuration
is valid. Local development may instead set one `CACHE_URL`.

## Local commands

Install dependencies when setting up the service:

```bash
uv sync --frozen --group dev
```

Rerun this command after moving the checkout or when `jobs/.venv` contains a
stale interpreter path. Do not point Jobs at or copy a virtual environment
from another worktree; each checkout is rebuilt from `jobs/uv.lock`. If an
installed launcher still references the old absolute path, force a lockfile-
identical rebuild with `uv sync --frozen --group dev --reinstall`.

Run the complete Jobs quality gate from the repository root. The runner has no
dependency-installation, migration, or persistent service-startup side effects:

```bash
./scripts/run-gates.sh jobs
```

The equivalent service-local checks are:

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
uv run pytest -q
```

Use `uv run ruff format src tests` deliberately when formatting; verification
commands never rewrite source.

Start the local stack:

```bash
uv run --frozen --no-sync start
```

This optional profile starts RabbitMQ on `127.0.0.1:55672`, Redis on
`127.0.0.1:56379`, the worker, one Beat scheduler, and the Jobs API on
`127.0.0.1:7302`. It does not install dependencies or apply database
migrations. Run it only when exercising uploads, parsing, background work, or
Zotero synchronization. Flower is separately available on
`127.0.0.1:7307` with `./scripts/start_flower.sh`.

For object storage, Jobs uses the same isolated remote dev S3 bucket as Server,
with matching values in the two ignored `.env` files. Scholens does not start
MinIO. Never use the production bucket or production workload credentials in
the local Jobs profile.

Run an opt-in real MinerU check with a local PDF:

```bash
uv run python scripts/smoke_mineru.py "/absolute/path/to/test-paper.pdf"
```

The smoke test uses real provider quota and is intentionally excluded from CI.
It prints the `submit`, `upload`, `poll`, `download`, and `archive` stages
independently, plus safe IDs, timings, output size, and classified diagnostics.
It never prints credentials or the signed upload URL.
