# 0016 — Lossless Reader reflow and lazy full translation

Status: Accepted
Date: 2026-08-14
Owners: Scholens

## Problem

The PDF canvas is accurate and remains the canonical desktop reading surface,
but fixed paper geometry is costly on phones. Pinch zoom, horizontal scanning,
and selection handles leave too little room for translation. Replacing the PDF
with model-written prose would improve layout at the cost of correctness,
traceability, and a second paper authority. Translating an entire upload in
advance would also spend credits on content the reader may never open.

The existing parser pipeline is already explicit and must remain unchanged:
PyMuPDF first analyzes every file; digital PDFs use `pymupdf4llm`, then
MarkItDown, MinerU rescue, and deterministic PyMuPDF text; scanned PDFs go
directly to MinerU. Reflow consumes the canonical Markdown produced by that
pipeline and is not another parser or extraction fallback.

## Decision

Every successful PDF ingestion schedules one independent `document_reflow`
DurableJob through the Server outbox. Scheduling is fail-open relative to PDF
completion: the paper becomes readable even if reflow cannot be queued or
generated. Reused completed Documents also ensure a reflow job when they enter
a new ingestion flow. A user may retry only a failed reflow; duplicate retries
return the active artifact instead of creating parallel jobs.

The Jobs worker reads canonical Markdown from private S3 and splits it into
ordered source units while preserving fenced code and display math. The shared
provider-neutral `reflow` AI profile may classify each unit as title, authors,
heading, paragraph, list, quote, equation, table, figure, code, or references.
It may not rewrite, summarize, translate, merge, drop, duplicate, or reorder
source content. The worker accepts AI output only when every source index occurs
exactly once and in ascending order; an invalid or unavailable AI response uses
the deterministic local classifier for that chunk and records a warning.

Server validates the callback owner, job, Document, source fingerprint,
continuous indexes, unique stable block IDs, and the complete ordered
whitespace-normalized content fingerprint before committing blocks. The
artifact and its current job are separate from PDF processing status. A failed
reflow never marks a Document or ingestion failed. Stable blocks retain a
best-effort one-based PDF page projection so readers can return to the source
page.

Reader exposes `view=reflow`; omitted or invalid `view` means `pdf`. The PDF is
the canonical default. `translate=full` is an independent shareable reading
state. The reflow surface is responsive document flow, not a reproduction of
PDF coordinates, and it uses semantic design tokens in Light and Dark. Remote
Markdown images are represented without fetching their URL; the original PDF
remains the authority for figures and exact visual layout.

Full translation operates per persisted reflow block. The browser sends only
the Document and block identifiers to
`POST /api/v1/papers/{document_id}/reflow/blocks/{block_id}/translations`.
Server authorizes the paper, reads the completed block, and delegates to the
same translation workflow, preferences, provider profile, SSE protocol,
durable PostgreSQL result store, Redis single-flight lease, rate checks, and
capacity controls as selection translation. Cache identity additionally owns
`context_kind=reflow_block` and `block_id`, so it cannot collide with a
selection result.

The browser uses `IntersectionObserver` with a bounded near-viewport margin and
a hard maximum of two concurrent block streams. It cancels the session when
full translation is disabled, the Document changes, or translation preferences
change. Completed blocks are durable cache hits on later visits and bypass
provider capacity and Token Credit checks after authorization. Failed blocks
retry independently; already rendered original content never disappears.

## Alternatives considered

- Generate replacement prose for the whole paper. Rejected because a language
  model would become a competing content authority and could silently omit or
  alter evidence.
- Change or replace the parser for reflow. Rejected because extraction and
  presentation are separate responsibilities and the established fallback
  order already owns PDF quality recovery.
- Store one HTML document returned by the model. Rejected because it is harder
  to validate losslessly, unsafe to render directly, difficult to page-map, and
  prevents block-level translation caching.
- Translate every block immediately after upload. Rejected because it charges
  for unread content and delays a transformation that is independent from PDF
  availability.
- Accept source text from the browser for full translation. Rejected because
  the client could tamper with content and the server already owns the exact
  authorized source block.
- Use one unbounded client stream per visible block. Rejected because fast
  scrolling could create a provider burst and weaken predictable capacity.

## Consequences

`document_reflows` and `document_reflow_blocks` are Document-derived Scholens
data and cascade with the Document. The current artifact references one
DurableJob, while previous jobs retain immutable execution history. Translation
results remain separate reusable derivatives and cascade with the Document.

The Server owns cross-module coordination under `bootstrap/adapters`; the
reflow application module owns authorization and retry policy; Jobs owns
classification execution; Reader owns only queries, URL composition, viewport
scheduling, and presentation. Provider names and model IDs never appear in
product contracts. Deployment selects model URI, thinking mode, and thinking
effort through the central `reflow` and `translation` AI profiles; both default
to DeepSeek V4 Flash with thinking disabled and effort `none`.

## Validation

Jobs tests cover code/math-safe source splitting, request chunk bounds, stable
IDs, accepted AI classifications, and deterministic invalid-AI fallback.
Server tests cover authorization, durable scheduling, failed-only retry,
callback integrity, source-preserving persistence, PDF-completion independence,
and server-owned block translation. Reader unit tests cover URL defaults and
the two-stream scheduler; Storybook covers original, translated, streaming,
error, narrow mobile, Dark, and the interactive full-translation toggle.
Generated OpenAPI types, architecture checks, full service tests, Storybook
accessibility tests, production builds, and route E2E form the release gate.
