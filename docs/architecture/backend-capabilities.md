# Backend capability architecture

Scholens exposes one set of business capabilities through several adapters.
The public HTTP API, the in-process Agent tools, internal job callbacks, and the
inbound MCP server are entry points; none of them owns paper, project, billing,
or Zotero business rules.

```text
HTTP / Agent / MCP / job callback
                 |
                 v
 authentication + Actor
 permission/tool preflight
 OperationContext provenance
                 |
                 v
          ApplicationExecutor
                 |
                 v
        module application use case
                 |
          domain policy + ports
                 |
                 v
 infrastructure adapters (PostgreSQL, S3, Stripe, Zotero, jobs, LLM)
```

## Stable contracts

The browser-facing API is mounted once at `/api/v1`. Provider callbacks are
under `/webhooks/v1`, and worker-only operations are under `/internal/v1`.
Production routing deliberately does not expose `/internal/v1`.

Public resources use canonical identifiers:

- `document_id` identifies a paper everywhere. Association-row identifiers
  are named explicitly and are never presented as paper identifiers.
- Collections return `{ "items": [...], "next_cursor": "...",
"previous_cursor": "...", "total_count": 0 }` when bidirectional navigation
  is part of the product. Cursors are opaque, signed, user- and query-bound
  keysets with a stable identifier tie-breaker; offset values are not disguised
  as cursors.
- Resource creation returns `201`, accepted asynchronous work returns `202`,
  and deletions without a response body return `204`.
- Project browsing is an aggregate projection: cards expose paper, private
  conversation, visible output, collaborator, and activity facts without
  per-project count queries. Project paper and output collections use the same
  signed, user-and-filter-bound keyset contract as Library collections.
- Paper ingestion, Zotero imports, and generated artifacts accept
  `Idempotency-Key`. Reusing a key with a different request returns `409`.

The reviewed public surface is stored in
`server/openapi/v1-contract.json`. A contract test fails whenever a route is
added, removed, renamed, or changes method without an intentional snapshot
update. `python -m app.scripts.export_public_openapi` regenerates both the full
public schema and this reduced route/method review surface; reviewers must still
confirm that every resulting public route is intentional.

## Module rules

Each business module owns `domain`, `application`, and `infrastructure`
packages.

- `domain` contains pure rules and cannot import web frameworks, persistence,
  SDKs, or another module's infrastructure.
- `application` owns complete use cases and transaction intent. It depends on
  protocols and public application contracts, never concrete adapters.
- `infrastructure` implements ports. Repository methods flush but do not
  commit a caller-owned request transaction.
- `transport` validates and translates protocols only. HTTP, Agent, job, and
  MCP adapters receive the same `ApplicationExecutor`; they never
  receive a SQLAlchemy `Session`, select adapters, or duplicate business
  rules.
- `bootstrap/capabilities.py` is the canonical session-bound application
  surface. `bootstrap/container.py` is the only composition root that selects
  concrete adapters.
- Cross-module work is coordinated through application ports/facades and
  wired in the composition root. ORM relationship imports used only under
  `TYPE_CHECKING` are mapping metadata, not business dependencies.

`ApplicationExecutor.query` closes without committing.
`ApplicationExecutor.command` and `command_async` commit exactly once after a
successful operation and roll back on failure. Nested executor operations are
rejected.

External I/O must not run inside an open database transaction. Workflows use:

```text
command: prepare/reserve
        -> commit
external call or stream
        ->
command: complete
failure -> command: fail/release
```

Document reflow follows the durable form of this rule. It begins only when the
user explicitly creates an attempt. Server preflights the user's enabled MinerU
connection, commits the reflow artifact, DurableJob, and dispatch outbox
together, and gives the worker only an internal credential URL. After claiming
the job, the worker fetches the current revision-scoped token, submits the
original PDF to MinerU, and maps its stable ordered `content_list.json` to
continuous semantic Markdown blocks outside the transaction. The signed
callback resumes a short SYSTEM operation, applies the provider outcome only
when its revision still matches the current connection, validates the source
fingerprint, block order, source spans, and asset references, then atomically
replaces the artifact's ordered blocks and assets. Reflow failure, including
an isolated missing-asset degradation, remains independent from PDF ingestion
success.

Chat streaming, paper ingestion, Research generation, onboarding, Stripe, and
Zotero import/sync follow this shape. Agent and MCP paper tools obtain a fresh
short operation for every tool call rather than retaining a session for the
life of a conversation.

## User-owned integrations

`GET|PUT|DELETE /api/v1/me/integrations/{provider}` is the one public
connection contract for MinerU and optional MCP providers. Responses expose
status, revision, verification information, and a masked secret hint, never the
credential. Scholight remains built in. The superseded connector CRUD surface
and shared MinerU environment credential do not exist.

Connector MCP tools retain the native names returned by their owning server;
Scholens does not add provider prefixes or maintain aliases. Resolution is
deterministic and rejects a later tool whose name is already reserved or exposed.
The canonical Scholens tool `search_saved_papers` searches papers already
accessible in the current Library, Project, or selected-paper context, while
Scholight's native `search_papers` searches for external literature. This naming
keeps stored-corpus retrieval distinct from discovery without introducing a
second connector contract.

Server encrypts integration credentials at rest with the deployment-owned
`INTEGRATION_CREDENTIAL_ENCRYPTION_KEY`. A worker can decrypt nothing itself:
only a signed request for a currently running, owner-scoped PDF or reflow job
can retrieve the exact MinerU revision. The secret is not part of Celery
payloads, callbacks, operation journals, logs, or telemetry. Callback outcomes
are revision-bound, preventing an old attempt from marking a replacement token
invalid.

Provider failures preserve stable product meaning. Missing credentials request
the MinerU integration; authentication failures mark only the matching revision
invalid; rate limits and provider unavailability remain retryable; insufficient
content and unsafe archives are distinct non-generic terminal results. Public
projections retain only bounded safe codes and messages.

## Authentication, permission, and operation provenance

Authentication, authorization, and attribution are deliberately separate:

- sanchezcloud-identity sessions authenticate browser users; Scholens AccessKeys
  authenticate MCP clients;
- `WorkspacePermission` and `ToolAccess` determine which catalog tools are
  visible and executable;
- `Actor` plus Domain policy authorizes the concrete resource;
- immutable `OperationContext` records only trace, direct initiator, typed
  origin, and a non-sensitive credential reference.

Changing an Operation origin or credential must never change a Domain
authorization result. Raw credential, signature, OAuth callback, and webhook
verification complete before an `OperationContext` is constructed.

Every product-changing Application command receives an explicit
`operation: OperationContext`. Its private, session-bound `OperationJournal`
appends stable business actions in the same UnitOfWork as the business write.
Queries, rejected operations, no-ops, technical leases, and replayed tool
invocations do not create Journal entries. The Journal is append-only and has
no public read capability or transport endpoint.

Conversation turns are USER root operations. A turn owns an immutable user
prompt and its typed context snapshot, while model responses, tool calls,
citations, and generated titles are AGENT child operations that retain the turn
correlation. Editing creates a sibling turn and selects that new path; it never
rewrites the source prompt. A retry creates a response variant under the active
leaf, and selecting a response variant does not rewrite the prompt. Jobs persist
only their origin operation and correlation UUIDs, then callbacks resume a new
SYSTEM operation after signature and owner verification.

A Conversation title sidecar starts with its first turn and is applied once.
It never blocks answer persistence or the public `response_ready` event. Later
turns may retry only while the title remains the default; an explicit user title
always wins over a concurrent generated title.

## Canonical tool catalog

Every model-visible research workspace tool is defined once in
`server/app/tooling/workspace.py`. A `ToolDefinition` owns its stable name,
description, Pydantic input model, execution kind, and application handler.
Independent Conversation and MCP profiles select definitions from the same
catalog; transports never copy schemas or handlers.

## Single conversation agent

Home, project, and paper conversations all execute through one
`ScholensConversationAgent`. The conversation scope supplies initial context and
the default paper collection; it does not select a different runtime or tool
set. Pydantic AI owns only the model/tool loop and model event decoding.
Scholens retains ownership of authentication, tool visibility, resource
authorization, operation provenance, argument validation, idempotent dispatch,
source registration, citation validation, persistence, limits, and
cancellation.

The model receives an injected absolute time for the request's validated IANA
time zone, so current-date answers do not rely on model memory. Tool results are
bounded and projected before returning to the model. `Agent.iter()` exposes
complete model and tool nodes to the harness: text from a response that calls a
tool completes as a `progress` item, while the accepted no-tool response
completes as the `final` item. Both use stable IDs and share a monotonic sequence
with sanitized activity records. The persisted trace contains ordered progress
and activity entries; progress is bounded before persistence, and final answer
text remains in the selected `ConversationResponse` row. Runtime-to-adapter communication uses the
public typed event models directly plus one private typed result envelope, so
there is no second untyped event protocol to drift. Empty assistant items are
rejected and a turn cannot complete without visible final content.

The public Conversation stream exposes item lifecycle events, sanitized
activity, final-only server-generated references, a persisted `response_ready`
snapshot, an optional turn-suggestion update, and one terminal event. Raw
reasoning, provider heartbeats, tool identity, full parameters, and tool return
payloads remain internal diagnostics.

The conversation aggregate has a reset-first Turn/Response tree rather than a
compatibility wrapper around messages. Conversation and turn selectors define
one active root-to-leaf path, and a path revision invalidates stale pagination.
Only the active leaf exposes its response variants and permits retry or response
selection. Starting a normal child deletes its parent's unselected response
variants and stale suggestions; edited prompt siblings and their selected
descendant suffixes remain durable. Agent history contains selected ancestors
only. Branch creation and selection restore the turn-owned paper context after
current authorization, and one response may run across the whole Conversation.
Completed, failed, and cancelled responses persist total duration separately
from their ordered worklog trace. The latest terminal attempt remains selected,
and the active leaf exposes terminal attempts so safe failure/cancellation state
and retry survive refresh without publishing raw exceptions.

Reader selections and annotation threads enter that same aggregate through
typed turn contexts. Personal Reader conversations are paper-scoped. Reader
conversations created while a Project is active remain private to the user but
are Project-scoped with the open paper in selected document context. Project
conversation listing may therefore filter by that context document; its signed
cursor binds actor, Project, context document, and page size. The browser never
downloads a broader collection to filter it locally.

Reader annotation collections return self-contained thread timelines. The
paper-level list carries each thread's derived presentation mode, ordered
comments, comment count, last activity, status, anchor, and current actor
capabilities. It is ordered by source position rather than recent activity, so
replying or selecting never moves a thread in the document rail. Filters for
audience, presentation mode, and status are authorized and applied by the
Server, with open threads as the default. The thread-detail endpoint remains a
canonical single-thread resource for direct consumers. Presentation mode is
derived from audience and comment count and is never another persisted source
of truth.

Reader selection translation is a paper-authorized streaming workflow.
`GET|PUT /api/v1/me/translation-preferences` owns source language, target
language, custom instructions, automatic-selection behavior, bilingual or
translation-only full-translation presentation, reference opt-in, and the
translation-marker preference;
`POST /api/v1/papers/{document_id}/selection-translations` streams standard
`start`, `delta`, `complete`, and `error` events. The workflow checks paper
access before looking up a durable result, so shared result reuse never becomes
an authorization side channel.

Completed translations are persisted without source text. Their SHA-256
identity binds document, normalized source, title, language direction,
instructions, prompt revision, and AI profile revision. PostgreSQL owns the
completed result; Redis owns only rate limits, concurrency leases, and a short
single-flight lease. Cache hits bypass provider quota and AI capacity checks.
Only the request holding the single-flight lease may call the provider and
settle usage.

For reflow blocks, the normalized source is the repaired `render_markdown`
rather than the parser's raw Markdown. This keeps the durable cache aligned with
the evidence-validated text actually shown to the reader while the browser
continues to send only the authorized block identity.

Follow-up suggestions are a non-critical turn sidecar started before answer
streaming. The model call runs outside an application transaction; the final
short write locks the conversation and persists only while the turn is still
latest, preventing slow work from resurrecting stale suggestions. Inputs are
limited to the current query, locale, three recent selected turns, and
authorized scope titles; the current answer, ordered worklog, provider output,
tool payloads, and document bodies are not suggestion context. The typed output
requires exactly three unique questions covering deeper inquiry, comparison or
verification, and practical use. A retry reuses the turn-owned result.

Conversation generation has one externally observable acceptance boundary.
Quota, access, immutable context resolution, rate limiting, and concurrency
acquisition run before product writes. The following short command atomically
creates the Turn/Response and selected path; for prompt branches it also restores
the source turn's paper-context snapshot. A command conflict releases the lease.
After commit, the first streamed event is `start`, so every later error belongs
to the persisted active leaf and remains safely retryable after refresh.

`ToolDispatcher` validates arguments and executes each tool through a fresh
`ApplicationExecutor` operation. Query tools never commit. Command tools commit
their business change and completed invocation ledger row atomically. Workflow
tools use an explicit external-I/O workflow and then persist the completed
result. Conversation write invocation identities include conversation, turn,
tool-call arguments, and tool name; MCP identities use the authenticated token
session and JSON-RPC request identity. Replays return the persisted result, and
conflicting argument reuse returns `tool_invocation_conflict`.

The inbound Streamable HTTP MCP endpoint is `/mcp`, outside the public OpenAPI
surface. Every request requires a Scholens AccessKey in the Bearer header.
The key's immutable permission snapshot determines the MCP `ToolAccess`; its
resolved Actor still passes through the same resource authorization as HTTP
and Conversation calls. MCP defaults paper operations to the authenticated
user's complete accessible paper collection. Protocol code only authenticates,
builds typed provenance, selects a profile, and delegates to
`ToolDispatcher`.

Only progress-owning infrastructure may commit independently. The executable
architecture whitelist contains narrow technical ledgers and dispatchers such
as the Stripe webhook ledger and durable Jobs outbox. They reserve progress in
a short transaction, perform external I/O with no Session, and finalize in
another short transaction. Product workflows, including Zotero, citation
recovery, discovery, document postprocessing, and billing, use
`ApplicationExecutor` stages; repositories themselves never commit.

Domain concepts have one canonical type name. Compatibility assignments such
as `OldAccess = NewAccessDecision` are forbidden by an architecture test; a
distinct projection type is allowed only when it carries genuinely different
data or responsibility.

## Replaceable search

`PaperSearchPort` is the stable application boundary. The current
`postgres_fts` adapter ranks accessible document metadata and passages using
PostgreSQL full-text search. `PAPER_SEARCH_BACKEND` is validated at startup.
A future embedding or hybrid implementation is added as another adapter and
selected only in the composition root; HTTP, Agent, and MCP contracts do not
change.

The search collection named `library` is a computed access view, not a synonym
for `LibraryPaper` membership. It contains the user's personal-library papers
plus papers available through Projects they own or collaborate on. Access is
re-evaluated for each operation, and the outer `Document` query keeps papers
that are reachable through several paths unique. Personal-library listing,
tags, storage accounting, and ingestion ownership continue to use
`LibraryPaper`; no Project paper is copied into the personal library.

## Library collection

The Library exposes two deliberately different collections:

- Papers are personal `LibraryPaper` memberships. Search, tag OR-filtering,
  stable keyset sorting, removal, download, and ingestion operate on that
  membership. Removing a paper removes the personal membership only; shared
  `Document` storage is reclaimed later only when no scope still references it.
  Tags are user-owned resources with create, rename, and delete lifecycle
  commands. Assignment updates replace the exact tag set for each selected
  Library Paper, including an empty set; the API does not expose parallel
  add-only and per-assignment removal protocols.
- Outputs are a read projection over the four existing `ResearchItemKind`
  values: `annotation_thread`, `citation`, `audio_overview`, and `data_table`.
  The bootstrap adapter applies canonical audience authorization and returns
  source audience/title metadata in one response. Annotation threads also carry
  a target Document independently of their personal or Project audience. The
  browser does not join permissions itself.

`GET /api/v1/library/summary` returns successful Paper and Output counts plus
the number of current ingestion lifecycles and failed ingestions that require
attention. Both list endpoints use signed Previous/Next keyset cursors bound to
user, collection, filters, sort, and limit. Paper sources enter through the discriminated
`POST /api/v1/paper-ingestions/sources` contract (`doi`, `arxiv`, or direct PDF
`url`); URL resolution and PDF validation remain server-owned. Failed jobs are
retried by creating a new durable job from the persisted source, never by
mutating the failed history row.

PDF uploads and source imports share one atomic acceptance boundary. A `202`
means the personal membership, source reference, durable job, and dispatch
outbox record are committed and the ingestion is already visible through the
Papers list union. The response is the canonical ingestion projection rather
than an upload-only acknowledgement. That union emits exactly one row per
personal membership: an active or failed ingestion replaces the completed
paper projection instead of being prepended as a second row. Unattached active
or failed reservations are pinned before completed rows on the first forward
page so every accepted file remains observable before it owns a Document.
Failed rows expose the preserved filename, bounded lifecycle stage, safe error
code, Retry, and remove actions; provider diagnostics stay server-side. Browser
content hashing is an early UX filter only; the Server's SHA-256 checks and uniqueness
constraints remain authoritative for repeated and concurrent uploads. `DELETE
/api/v1/paper-ingestions/{job_id}` owns cancellation; cancelled jobs reject
replay and ignore late worker callbacks. The worker reports bounded lifecycle
stages and heartbeats, while the Server owns terminal timeout/failure policy.

PDF completion persists extracted metadata, generated summary, and summary
citations on the canonical `Document`. It does not synthesize a paper-scoped
conversation or a fake user turn. Starting a conversation about a paper is an
explicit user operation and the conversation references that existing
Document-owned context.

## Billing usage projection

`GET /api/v1/billing/usage` returns the selected inclusive date-only period,
the effective plan, current resource usage, and plan limits. Storage accounting
is persisted and returned in KiB; public fields therefore use the explicit
`knowledge_base_size_kb` and `knowledge_base_size_remaining_kb` names. Clients
must convert those quantities from KiB rather than treating them as bytes.
`period_end` is the inclusive final day of the selected window, not a timestamp
or the next reset instant.

## Adding a capability or adapter

1. Define transport-neutral request/response contracts and a port in the
   owning module's `application` package.
2. Implement the use case once and test its policy, authorization, and
   idempotency behavior without HTTP.
3. Add or replace infrastructure adapters and wire them in
   `bootstrap/container.py`.
4. Expose the use case on `ApplicationCapabilities`; use a workflow only when
   external I/O requires explicit prepare/complete phases.
5. Give every real command a stable owning-module `OperationAction`, accept an
   explicit `OperationContext`, and append through its private Journal only
   when the gateway reports a true change.
6. For a model-visible capability, add one `ToolDefinition` and select it in
   the appropriate profiles. MCP code must not call repositories or HTTP
   routes.
7. Update the OpenAPI snapshot and add an end-to-end contract test when the
   public surface changes.

This boundary also applies when identity, Zotero, billing, or a future product
area is reorganized; `/api/v1` is a platform version, not a paper-only
namespace.
