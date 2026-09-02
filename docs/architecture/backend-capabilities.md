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
 infrastructure adapters (PostgreSQL, S3, Zotero, jobs, LLM; dormant Stripe)
```

## Stable contracts

The browser-facing API is mounted once at `/api/v1`. A future provider callback
must live under `/webhooks/v1`, but the current production release mounts no
public provider webhook. Worker-only operations are under `/internal/v1`, which
production routing deliberately does not expose.

Public resources use canonical identifiers:

- `document_id` identifies a paper everywhere. Association-row identifiers
  are named explicitly and are never presented as paper identifiers.
- Collections return `{ "items": [...], "next_cursor": "...",
"previous_cursor": "...", "total_count": 0 }` when bidirectional navigation
  is part of the product. Cursors are opaque, signed, user- and query-bound
  keysets with a stable identifier tie-breaker; offset values are not disguised
  as cursors.
- Authenticated callback payloads that fail their operation contract are
  durably marked failed before their Redis concurrency leases are released.
  Unexpected handler or database failures retain the lease for retry or the
  3600-second TTL instead of weakening concurrency protection for active work.
- Resource creation returns `201`, accepted asynchronous work returns `202`,
  and deletions without a response body return `204`.
- Project browsing is an aggregate projection: cards expose paper, private
  conversation, visible output, collaborator, and activity facts without
  per-project count queries. Project paper and output collections use the same
  signed, user-and-filter-bound keyset contract as Library collections.
- MCP Project-member and paper-containing-Project collections are bounded
  keyset pages with signed actor-and-scope-bound continuations. Their page size
  may change between requests; the existing HTTP routes retain their complete
  collection responses.
- MCP Project-member rows use JSON-byte-bounded identity previews and retain
  immutable user IDs for subsequent changes. Member update and ownership
  transfer tools resolve the target through one authorized member lookup and
  return compact ID/permission receipts instead of echoing mutable identity or
  the complete Project. HTTP collaborator reads retain their full response.
- MCP Project summary pages return at most 25 rows, and Project-paper summary
  pages return at most 10 rows, even when a compatible client requests a larger
  maximum. Project descriptions and large paper metadata fields are JSON-byte
  bounded previews; list results retain their established item fields and add
  `content_truncated` plus retrieval `guidance`. Signed continuations preserve
  the remaining rows, while the HTTP Project and Reader contracts keep their
  complete values.
- MCP annotation-thread lists return at most 50 source-ordered summaries from
  a SQL `limit + 1` keyset page. Their signed cursor binds actor, filters, and
  ordering; summaries preserve `comment_count` but omit comment bodies, bound
  quote text at the encoded-JSON boundary, and retain only the first PDF anchor
  rectangle. `get_annotation_thread_page` continues complete discussions, and
  the HTTP Reader list keeps its self-contained timelines.
- MCP annotation mutations return a bounded thread summary and obtain comment
  count, last activity, foreign-reply state, and resolve eligibility through
  scalar queries. They never load the historical comment collection. The HTTP
  update capability retains its complete response contract.
- Paper ingestion, Zotero imports, and generated artifacts accept
  `Idempotency-Key`. Reusing a key with a different request returns `409`.
- `POST /api/v1/search/conversations` is the private lexical history-search
  contract. Its signed cursor is bound to actor, normalized query, and page
  size. Results contain the existing conversation summary plus the highest
  priority matched field and an optional bounded plain-text snippet; telemetry
  records only query length, result count, cursor presence, and duration.

Conversation search authorizes before retrieval and excludes archived rows.
A recursive PostgreSQL CTE begins at `selected_root_turn_id` and follows only
`selected_child_turn_id`; user-message matches therefore come only from the
visible branch, and assistant matches join only each active turn's
`selected_response_id`. Current Project or Document titles are the searchable
scope label, with the durable conversation snapshot as fallback. Title/scope
trigram expressions provide short-query and typo tolerance, while `simple`
PostgreSQL full text plus substring matching supports English and Chinese
message content. Ranking is deterministic: title, scope, user question, then
assistant response, followed by relevance, update time, and stable ID. This is
a direct projection over canonical conversation tables, not a second content
store or semantic index.

The reviewed public surface is stored in
`server/openapi/v1-contract.json`. A contract test fails whenever a route is
added, removed, renamed, or changes method without an intentional snapshot
update. `scholens contract export` regenerates both the full
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

Project invitation email is the Server-owned durable form of this pattern. The
create and manual-resend commands commit an invitation with `pending` delivery
state and return immediately. An API-lifespan supervisor claims bounded batches
with `FOR UPDATE SKIP LOCKED`, performs Aliyun DirectMail I/O outside the
transaction, then records `sent`, a retry time with exponential backoff, or
terminal `failed`. Expired leases are recoverable across replicas. Provider
exceptions are reduced to low-cardinality safe codes; recipient addresses,
message bodies, signed tokens, and raw provider errors never enter logs or
metrics.

The provider boundary is intentionally at-least-once: a process may stop after
Aliyun accepts a message but before Scholens commits `sent`. A recovered attempt
can therefore send the same revision again. The duplicate carries the same
short-lived link, and acceptance still consumes the invitation once; the system
does not claim impossible exactly-once delivery from an external mail API.

The product sender is provider-neutral and asynchronous. Aliyun is its current
adapter, with SDK retries disabled and bounded connection/read timeouts.
Identity email continues through the distinct `sanchezcloud-identity` sender;
the two interfaces share only the `SCHOLENS_ALIYUN_DM_*` account configuration
and `CLIENT_DOMAIN`.

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

Chat streaming, paper ingestion, Research generation, onboarding, and Zotero
import/sync follow this shape. The dormant Stripe implementation follows the
same boundary but is not composed into the first-release application. Agent and
MCP paper tools obtain a fresh short operation for every tool call rather than
retaining a session for the life of a conversation.

## User-owned integrations

`GET /api/v1/me/integrations` is the unified connection inventory. Credential
providers, including MinerU, OpenAlex, and optional MCP providers, use
`PUT|DELETE /api/v1/me/integrations/{provider}`. Zotero is an OAuth
`reference_manager` and deliberately uses its dedicated authorization and
disconnect endpoints. Responses expose status, revision, verification
information, and non-secret metadata, never the credential. Scholight remains
built in. The superseded connector CRUD surface, shared MinerU environment
credential, and independent plaintext Zotero connection do not exist.

OpenAlex is a user-owned search-category connection but is not an MCP
connector. Server fixes its endpoint to `https://api.openalex.org`, verifies a
saved or re-enabled key against `/rate-limit`, and calls the official REST API
for DOI/PDF resolution, external search, author works, and citation graphs.
Each request reads the current actor's key and revision in a short query,
performs provider I/O outside the transaction, and writes usage or invalidation
only when that revision is still current. The key is sent only as the required
`api_key` query parameter and is excluded from URLs in logs, exceptions,
telemetry, journals, DTOs, and object representations.

Connector MCP tools retain the native names returned by their owning server;
Scholens does not add provider prefixes or maintain aliases. Resolution is
deterministic and rejects a later tool whose name is already reserved or exposed.
The canonical Scholens tool `search_scholens_knowledge` searches papers,
passages, annotations, comments, and existing outputs already accessible in an
explicit Library, Project, paper, or all-accessible scope, while
Scholight's native `search_papers` searches for external literature. This naming
keeps stored-corpus retrieval distinct from discovery without introducing a
second connector contract. Each requested producer contributes one bounded
window of at most 25 candidates per tool call. A signed composite continuation
retains the independently consumed paper rank, annotation keyset, and output
keyset, so callers can continue beyond the first producer window without gaps
or duplicates. The continuation binds the actor, query, scope, kinds, paper
filters, sort, and requested page size. Existing-output search uses scalar SQL
catalog summaries rather than hydrating complete Research items, including for
paper scope. Paper producers likewise select only bounded title, abstract,
summary, timestamp, and matching-passage scalars; they never hydrate full
Document content or metadata arrays for a composite search page.
Annotation search selects bounded thread scalars and at most three matching
comments per thread and 200 comments per query page; it never loads complete
comment relationships. Library scope is exact personal membership and excludes
Project-only annotations and outputs; Project scope is exactly one Project;
paper scope includes personal context plus at most the explicitly selected
Project; all-accessible scope spans every currently authorized source.

Server encrypts integration credentials at rest with the deployment-owned
`INTEGRATION_CREDENTIAL_ENCRYPTION_KEY`. A worker can decrypt nothing itself:
only a signed request for a currently running, owner-scoped PDF or reflow job
can retrieve the exact MinerU revision. The secret is not part of Celery
payloads, callbacks, operation journals, logs, or telemetry. Callback outcomes
are revision-bound, preventing an old attempt from marking a replacement token
invalid.

Zotero's OAuth request-token secret is encrypted in a separate short-lived,
one-time row. Its callback accepts only the original local return path and
verifies the issued long-lived API key before storing it in
`IntegrationConnection`. Jobs receives that key only through the same claimed,
owner-, operation-, provider-, and revision-scoped internal boundary. Generic
credential writes are rejected for OAuth providers.

Provider failures preserve stable product meaning. Missing credentials request
the MinerU integration; authentication failures mark only the matching revision
invalid; rate limits and provider unavailability remain retryable; insufficient
content and unsafe archives are distinct non-generic terminal results. Public
projections retain only bounded safe codes and messages.

OpenAlex exposes the parallel stable failures
`openalex_credential_required`, `openalex_credential_invalid`,
`openalex_rate_limited`, and `openalex_unavailable`; a work-level `404` retains
not-found meaning. DOI import validates the DOI before opening the credential
boundary and uses only OpenAlex-provided open PDF locations. Upload, arXiv, and
direct PDF URL paths do not read the connection. Citation hydration is
Crossref-first: a complete Crossref result performs no OpenAlex credential
read, partial results merge only missing OpenAlex fields, and no connection
leaves the partial Crossref result usable.

## Zotero asynchronous data flow

Zotero browsing is a Server workflow: it decrypts the current connection for a
single remote call outside a database transaction, enforces personal-library
item types and Zotero's 100-item page ceiling, then returns a signed cursor
bound to owner, search, collection, type, sort, and limit. Library items expose
only stable metadata, current import state, and `stored_pdf`,
`resolvable_source`, or `unavailable` source availability.
Web follows the independent collection cursor beyond the first 100 collections.
For source availability, Server queries complete attachment pages only for the
currently visible papers. A per-paper safety limit produces a stable dependency
failure instead of silently treating the unscanned remainder as no PDF.

Import and sync acceptance are short application commands. They enforce
connection, quota, ownership, idempotency, and concurrency; then commit one
`ZoteroOperation`, DurableJob, and outbox row and return `202`. The broker
acceptance transaction locks the user's connection, so import and sync share a
single active-operation slot. Status projects the active kind and ID without
exposing the generic job payload.
The task payload contains no API key. After the worker claims the operation, it obtains
the current revision-scoped credential, performs Zotero reads and PDF
validation, and sends idempotent signed progress and item callbacks. Server
alone creates normal paper-ingestion jobs or appends annotation threads. An
operation may finish partially, and cooperative cancellation is terminal even
when a provider response arrives later.
Both services explicitly close each Zotero HTTP session on normal and exceptional
paths; the public-PDF resolver does the same across redirect and SSRF rejection
paths.
Each terminal callback first atomically claims an expiring callback-processing
lease. A terminal, cancelled, concurrent, or replayed callback exits before
provider-outcome recording or any import, annotation, journal, or storage
mutation. Callback keys, staging paths, metadata, annotation content, and total
serialized size are validated against bounded internal contracts.
Jobs incrementally enforces the shared 12 MiB compact-JSON budget before a
provider-controlled batch can accumulate in memory and validates the exact body
again before delivery. Sync reserves 4 MiB for automatic imports; annotation
targets beyond its projection are not reported or marked attempted. Manual
imports preserve a small stable failure for each requested key that cannot fit,
and an unreported prepared staging object is removed immediately. A truncated
automatic page remains uncaught-up, so its cursor advances only through the
returned resolved prefix.
The renewable claim uses a 30-second heartbeat and 15-minute lease around a
12-minute Server processing bound; Jobs waits 13 minutes for the signed HTTP
result. Import planning precedes any staged download, and Server consumes one
PDF at a time with claim checks after download and capacity acquisition. A lost
claim releases the capacity permit before upload. Ambiguous delivery timeout or
request cancellation preserves `zotero-imports/` staging for retry and the
two-day lifecycle instead of racing a Server reader.

Manual sync includes only already imported Zotero items. Scheduled sync is
eligible only for Researcher and uses Zotero library/item versions for
incremental annotation work. Automatic import is a separate default-off
preference: enabling it snapshots the current library version, scheduled work
requests a bounded 50-item ascending page, and Server persists a secondary
position only through the contiguous success/permanent-skip prefix. Temporary
provider, download, or quota failures stop advancement and are retried. Losing
Researcher pauses both automatic behaviors without clearing
the preference. Disconnecting removes future access but not imported Documents,
Library memberships, annotations, operations, or journal records.
Annotation targets are fairly ordered by the last attempt, so a failed first
500 cannot starve later papers. Every success or failure updates the attempt
time; only success updates `last_synced_at`. Missing Zotero items or attachments
move that link to `source_unavailable` and out of automatic annotation polling
while preserving Scholens data.

## Authentication, permission, and operation provenance

Authentication, authorization, and attribution are deliberately separate:

- sanchezcloud-identity sessions authenticate browser users; Scholens AccessKeys
  authenticate MCP clients;
- the Scholens browser bootstrap adapter rotates the shared refresh session and
  resolves the product Actor in one response without moving either ownership
  boundary;
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

Durable Conversation workers enter through a SYSTEM Job operation, then
attribute model, tool, citation, and title writes to causally linked AGENT
resumptions under that Job origin and the retained turn correlation. A Job root
operation remains SYSTEM-only.

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

The catalog is designed around a Project as the durable knowledge boundary for
an external research repository. `create_project` and `get_project` return its
immutable UUID, `scholens://` URI, Web URL, and ready-to-paste binding Markdown.
Every later call accepts immutable IDs rather than guessing from titles.

The current shared profile contains 62 tools. With all four workspace
permissions, the remote HTTP MCP profile adds `prepare_paper_upload`, for 63
total. The Conversation profile instead adds the internal-only
`wait_for_jobs`, also for 63 total. The local stdio bridge hides the remote
upload primitive and supplies `upload_local_paper`, so it presents 63 tools to
a fully authorized key; narrower keys see only their authorized subset. The
surface covers:

| Capability                                                   | Remote tools | Boundary                                                 |
| ------------------------------------------------------------ | -----------: | -------------------------------------------------------- |
| Stored paper search, bounded content, citation, and download |            8 | No internet discovery                                    |
| Projects, papers, membership, invitations, and ownership     |           19 | Resource authorization after coarse Access Key filtering |
| Personal Library, sharing, and tags                          |           16 | Library state remains user-owned                         |
| Known-source ingestion, upload preparation, and jobs         |            7 | Bounded waiting, batch acceptance, stable idempotency    |
| Annotation threads and comments                              |            9 | Personal or one-Project audience                         |
| Existing research outputs                                    |            4 | Read-only; no generation tool                            |

Agent-facing catalog validation requires a human-readable title, typed output,
behavior annotations, decision-oriented description, and a description on
every top-level input field. Descriptions state when to use a tool, when not to
use it, what it returns, and the intended next step. Synchronous and asynchronous
query, command, and external-I/O workflow kinds remain explicit internally;
asynchronous reads remain public MCP queries. MCP `readOnlyHint`,
`destructiveHint`, `idempotentHint`, and `openWorldHint` reflect actual behavior
rather than transport method names.

`read`, `write`, `manage`, and `delete` Access Key permissions expose only the
relevant subset. `manage` separates collaboration and public-sharing authority
from ordinary content writes. Each handler still rechecks Project, paper,
Library, annotation, job, invitation, or output access; an Access Key never
grants a resource the user could not otherwise reach.

State-changing invocations support a caller-stable idempotency key and retain a
completed invocation result when that result is safe for durable replay.
Destructive, public-sharing, email-delivery, and access-control tools use a
two-call confirmation protocol. The first call commits only a bounded impact
preview and opaque token. The token is stored as a hash, expires after ten
minutes, is single-use, and binds actor, credential, tool action, normalized
business arguments, and a live-state fingerprint. Raw confirmation challenges,
plaintext public bearer tokens, and signed upload URLs are never copied into the
invocation ledger. Confirmation arguments and live-state graphs cross one
strict recursive JSON-normalization boundary, so nested typed response models,
UUIDs, timestamps, and enums retain deterministic digest semantics while
ambiguous containers and non-finite numbers fail closed.

MCP resource links make durable objects addressable without forcing an Agent
to repeat discovery calls. Static resources expose Library and Project
manifests; templates expose Project, paper, annotation-thread, and existing
research-output records. Reads are re-authorized and bounded to 200,000 UTF-8
bytes, with typed continuation calls when a representation is too large. Each
resource kind first builds a typed public manifest and then crosses
the same strict JSON-normalization boundary; normalization never substitutes
for field projection or redaction. Invalid URIs, missing resources, access
denials, and internal failures use bounded JSON-RPC errors. Raw validation
diagnostics and application model representations remain server-side.
Annotation-thread and research-output manifests select one authorized bounded
catalog row by immutable ID; they do not call the complete Research-item
getter and then discard its large fields.
Paper manifests use an authorized fixed-width metadata projection and a
database-bounded extracted-text prefix with scalar total-line/count facts.
They do not hydrate complete historical metadata or construct the lossless
64 MiB content snapshot to return a 16 KiB Resource preview.

Established complete-object MCP reads remain registered during a governed
rolling migration. `get_paper_page`, `get_library_paper_page`,
`get_annotation_thread_page`, and `get_research_output_page` provide lossless
canonical JSON continuation, while `list_library_paper_summaries` and
`list_research_output_summaries` provide bounded keyset catalogs. Resources
reference these replacements. The six legacy tools retain their historical
input/output shapes and runtime branches; their owner, telemetry, minimum
90-day window, and replacement are recorded in the deprecation registry.

## Single conversation agent

Home, project, and paper conversations all execute through one
`ScholensConversationAgent`. The conversation scope supplies initial context and
the default paper collection; it does not select a different runtime or tool
set. Pydantic AI owns only the model/tool loop and model event decoding.
Scholens retains ownership of authentication, tool visibility, resource
authorization, operation provenance, argument validation, idempotent dispatch,
source registration, citation validation, persistence, limits, and
cancellation.

The agent instructions encode an autonomy policy instead of a fixed tool
workflow: prefer solving with available tools when the answer depends on stored
knowledge, workspace state, user-specific resources, or external evidence;
inspect before claiming absence or inventing details; and treat clarification
as a last resort after cheap tool checks. A direct no-tool answer remains
allowed for purely conversational requests, current-date questions already
answered by the injected clock, and requests fully covered by server-validated
materials already in the prompt.

Scope supplies a center of gravity, not a capability wall. Global, project,
and paper conversations each receive a gravity paragraph that shifts default
attention (corpus-wide orientation, project-centered research, or deep reading
of the open paper) while remaining general-purpose and free to broaden or
narrow when the request needs it and tools permit. Manual conversation
`paper_context` edits and turn contexts refine attention and are injected into
the prompt, so the model sees the current selection shape instead of assuming
a default. The instructions also expose the resolved connector inventory:
attached connector tool names such as Scholight's `search_papers`, bounded
omission summaries, and a statement that authorized workspace tools are
available through their schemas. External literature discovery remains
connector-owned and is never a built-in catalog tool; when no discovery
connector is available, the agent says so instead of fabricating a search.

The model receives an injected absolute time for the request's validated IANA
time zone, so current-date answers do not rely on model memory. Tool results are
bounded and projected before returning to the model. `Agent.iter()` remains the
single Pydantic AI execution loop; the harness buffers complete model nodes and
classifies them by tool presence and normal termination, never by prose
heuristics. Text accompanying an ordinary runtime tool call may complete as
bounded `progress`. A response with no tool call and normal text termination is
the terminal answer; there is no model-visible finalization tool or structured
output envelope. The additive candidate route projects that terminal text after
classification, while clients that do not use it receive no provisional events.
The server still validates and strips the private citation protocol before the
canonical final item or persistence, but citation availability is deliberately
separate from answer availability. Empty visible content, copied private
protocol, provider stream corruption, and unexpected output tools remain hard
failures. Missing references, unknown keys, malformed markers, and visible
`[A1]`-style placeholders are citation-quality soft failures: the sanitized
visible answer is completed while invalid attribution metadata is dropped. A
source-backed answer records a typed citation summary
(`not_required`, `complete`, `partial`, `unavailable`, or `pending`) plus a
separate grounding status; an empty reference bundle means sources were found
but no sentence-level citation was safely established, not that every source
supports the answer. One completed grounded-answer inspection supplies the
sanitized text, valid references, trace counts, and publication state so those
paths cannot parse the private protocol differently.

Provider-native attribution is translated through the unified
`CitationNormalizer` boundary for DeepSeek/OpenAI-compatible output, OpenAI
annotations, Gemini grounding supports/chunks, Anthropic citation blocks, and
Bedrock citation spans. Every adapter maps back to the current server-owned
source registry; unknown provider identifiers are discarded. When native
metadata is absent, bounded post-hoc claim alignment considers at most 24
claims and three source candidates per claim and emits only deterministic
evidence matches. Similarity is a candidate ranker, never proof. An optional
small verifier callback is invoked only for uncertain candidates and shares the
two-second budget; verifier outcomes other than `SUPPORTED` remain unlinked.
The first implementation is synchronous and bounded; an optional future
`citation_update` event may enrich a completed response without changing its
answer.

Progress and final items use stable IDs and share a monotonic sequence with
sanitized activity records. The persisted trace contains ordered progress and
activity entries, while final answer text remains in the selected
`ConversationResponse` row. Runtime-to-adapter communication uses the public
typed event models directly plus one private typed result envelope, so there is
no second untyped event protocol to drift.

The public Conversation stream exposes item lifecycle events, sanitized
activity, final-only server-generated references (including an empty bundle with
an additive citation summary when evidence was retrieved but no attribution
survived), a persisted `response_ready` snapshot, an optional turn-suggestion
update, and one terminal event. Accepted
generations run in the dedicated Server-owned Conversation worker. A bounded
Redis Stream is only a replayable delivery log; PostgreSQL remains authoritative
for running and terminal Response state. Raw
reasoning, provider heartbeats, tool identity, full parameters, and tool return
payloads remain internal diagnostics.

The aggregate serializes generation only within one Conversation. Separate
conversations may hold concurrent accepted responses under the per-user
interactive limit; changing the active browser conversation detaches its local
subscription without cancelling that Server-owned work.

The conversation aggregate has one canonical Turn/Response tree rather than a
second message-shaped domain model. Any required compatibility translation
stays at a transport or persistence boundary. Conversation and turn selectors
define one active root-to-leaf path, and a path revision invalidates stale
pagination.
Only the active leaf exposes its response variants and permits retry or response
selection. Starting a normal child deletes its parent's unselected response
variants and stale suggestions; edited prompt siblings and their selected
descendant suffixes remain durable. Agent history contains selected ancestors
only. Branch creation and selection restore the turn-owned paper context after
current authorization, and one response may run across the whole Conversation.
Running, completed, failed, and cancelled active-leaf responses are serialized
so a new browser session can recover an in-flight subscription. Terminal
responses persist total duration separately
from their ordered worklog trace. The latest terminal attempt remains selected,
and the active leaf exposes terminal attempts so failure/cancellation state and
retry survive refresh. Stable failure code, kind, retryability, diagnostic ID,
and correlation ID are product metadata; raw exceptions and provider bodies are
not.

Reader selections and annotation threads enter that same aggregate through
typed turn contexts. Personal Reader conversations are paper-scoped. Reader
conversations created while a Project is active remain private to the user but
are Project-scoped with the open paper in selected document context. Project
conversation listing may therefore filter by that context document; its signed
cursor binds actor, Project, and context document. The browser never
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
of truth. A PDF text anchor accepts either the historical one-page projection
or ordered page segments. For a segmented anchor, `page_number` and `rects`
must equal the first segment, preserving indexed source order and compatibility
while the JSON position remains one annotation-thread value. The canonical
position validator caps geometry at 200 normalized rectangles in total across
all segments, preventing an additive page-by-page payload expansion.

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
creates the Turn/Response, selected path, DurableJob, and outbox dispatch; for
the first prompt it may also create the client-identified Conversation, and for
prompt branches it restores the source turn's paper-context snapshot. A command
conflict releases only a concurrency lease newly created by that acceptance
attempt; conflicting reuse of an active Response ID preserves the existing
generation's lease. `Prefer: respond-async` returns a `202` receipt after
commit. Without that preference, the POST returns a direct subscription
to the same durable generation, flushes a comment-only acceptance frame, and
then consumes Redis-ID events. The candidate-aware
`application/vnd.scholens.conversation-events` representation carries sanitized
partial answers and explicit cancellation; the established media type retains
its published event union. Neither path runs the agent inside the HTTP request.
Disconnecting a subscriber never cancels generation;
only the authorized cancellation command transitions the running Response and
job. Event subscriptions may reconnect from `Last-Event-ID`, but generation is
never automatically replayed. If a worker lease expires, the Response fails as
`generation_interrupted` because replaying a partially executed model/tool
sequence is not generally idempotent. A process-local notification wakes the
accepting API process's outbox dispatcher after commit; the bounded poll remains
the cross-process and recovery fallback.

`ToolDispatcher` validates arguments and executes each tool through a fresh
`ApplicationExecutor` operation. Query tools never commit. Replay-safe command
tools commit their business change and completed invocation ledger row
atomically. Workflow tools use an explicit external-I/O workflow and then
persist replay-safe completed results. Confirmation previews and definitions
whose results contain bearer or short-lived credentials execute without a
replay row. Conversation write invocation identities include conversation,
turn, tool-call arguments, and tool name; MCP identities use the authenticated
token session and JSON-RPC request identity. Replays return the persisted
result, and conflicting argument reuse returns `tool_invocation_conflict`.
Conversation-local argument validation failures return sanitized field errors
through a bounded `ModelRetry`; raw arguments stay private. Metrics include the
stable error code so repeated schema mismatches can be distinguished from
dependency and execution failures.

Durable-job tools use bounded server-side observation instead of model-driven
busy polling. Single ingestion, retry, exact job lookup, and bounded batch
ingestion accept `wait_seconds` with a 30-second default, `0` for an immediate
snapshot, and a 240-second maximum. Terminal jobs return immediately; a timeout
returns the latest owner-authorized snapshot, elapsed time, a stable outcome,
and machine-readable next-action guidance. Batch ingestion accepts at most 50
known sources with four-way concurrency and a 45-second acceptance budget,
then queries every accepted job together under one deadline. The Conversation
profile alone exposes `wait_for_jobs`, which observes up to 50 jobs with a
120-second default and may be repeated after a timeout. The MCP profile uses the
waitable submission and `get_job` contracts but does not expose this internal
orchestration tool.

The waiter opens one short query per capped-backoff observation and one final
deadline snapshot; it never holds a database transaction or connection while
sleeping. Conversation SSE emits comment-only keepalives during silent waits.
Client cancellation stops observation without cancelling the already-durable
job. Agent request or tool-call budget exhaustion has the stable
`agent_orchestration_limit_exceeded` code rather than a generic provider error.

Model-visible Job reads use a status-only repository projection and never load
or return durable Job `payload` or `result` JSON. Their established schema
continues to allow `result: object | null` for existing clients, while every MCP
projector emits null and sanitizes legacy replay rows. The product HTTP Jobs API
continues to expose its complete result contract. `list_jobs` is a signed
keyset-paginated status feed (20 by default, 50 maximum), while exact and batch
waits return stable resource identifiers for continuation through the owning
paper, Project, or research-output capability. Public projectors also sanitize
legacy invocation replays and replace response-copying actions with compact
receipts. The dispatcher enforces UTF-8 byte budgets after projection and
schema validation; the default success-envelope budget is 200 KiB and Job tools
use lower per-shape budgets. Batch source previews are truncated only at UTF-8
boundaries and are explicitly marked `source_truncated`.

Personal Library compatibility reads retain their complete historical
contracts. New callers use `list_library_paper_summaries`, whose durable-paper
keyset is capped at five bounded previews per page, and
`get_library_paper_page`, which exposes lossless canonical JSON in signed,
actor/resource/revision-bound UTF-8 ranges. Active ingestion state is retrieved
through `list_jobs`; rotating preview URLs stay outside the canonical document
as page-level access data. A 128 MiB revision-keyed LRU (64 MiB per entry)
avoids re-serializing paper, Library, annotation, audio, and data-table
representations on every page while keeping process memory bounded. Documents
above that supported ceiling fail explicitly with
`json_document_paging_limit_exceeded`; they never fall back to an O(N²) path.
Standalone active ingestions and durable papers form one composite keyset:
kind-tagged cursor positions cross the segment seam in both directions, pages
never exceed the requested limit, and active-ingestion counts use an
independent count plus a `limit + 1` scalar projection rather than ORM
hydration of the full active set.
Research pages calculate an authoritative revision across the owning item,
typed payload, identities, and annotation comments, plus a conservative
persisted-content serialization upper bound, before full hydration. Paper-text
pages perform the parallel lightweight retained-size preflight. Both caches
singleflight one key and reserve each distinct in-flight build against the
global retained budget before its factory runs. A shared cache kernel also
reserves explicit transient build memory and fails fast on recursive same-key
factories, so JSON normalization/encoding and text indexing cannot bypass the
retained-memory limit through concurrent misses. Paper regex search scans the
immutable cached string by start/end offsets, never copies an unbounded line,
and admits at most two concurrent scans per Server process, including cache-hit
requests. Match previews and JSON-string prefixes are sized incrementally with
bounded temporary memory.
`update_library_paper` returns a bounded, explicitly marked
preview and compact receipt so a valid write cannot be rolled back by an
oversized historical metadata echo; the page read closes the lossless path.

The inbound Streamable HTTP MCP endpoint is `/mcp`, outside the public OpenAPI
surface. Every request requires a Scholens AccessKey in the Bearer header.
The key's immutable permission snapshot determines the MCP `ToolAccess`; its
resolved Actor still passes through the same resource authorization as HTTP
and Conversation calls. MCP defaults paper operations to the authenticated
user's complete accessible paper collection. Protocol code only authenticates,
builds typed provenance, selects a profile, and delegates to
`ToolDispatcher`.

Every advertised MCP output schema accepts either the typed success envelope
or the structured business-error envelope, which the schema keeps so older
clients that still receive structured errors are not rejected. Runtime error
results (`isError: true`) intentionally omit `structuredContent` and carry
the full JSON error (code, kind, message, retryable, remediation, diagnostic
ID) only in the content text, so strict MCP clients skip schema validation of
errors and always surface the original Scholens error instead of a
-32602 schema-validation failure. The shared envelope declares `type: object`
at its root as well as the two object branches, so clients that enforce the
MCP `2025-11-25` Tool shape do not have to infer the root type through
`anyOf`. Public publication timestamps are serialized as RFC 3339 UTC values
even though the canonical database column stores calendar metadata without a
time zone.

Only progress-owning infrastructure may commit independently. The executable
architecture whitelist contains the durable Jobs outbox and the dormant Stripe
webhook ledger; the latter is retained with its payment code but has no mounted
route or runtime credentials. Such components reserve progress in a short
transaction, perform external I/O with no Session, and finalize in another
short transaction. Product workflows, including Zotero, citation recovery,
discovery, document postprocessing, and billing usage, use
`ApplicationExecutor` stages; repositories themselves never commit.

Domain concepts have one canonical type name. Compatibility assignments such
as `OldAccess = NewAccessDecision` are forbidden by an architecture test; a
distinct projection type is allowed only when it carries genuinely different
data or responsibility.

## Replaceable search

`PaperSearchPort` is the stable application boundary. The default
`postgres_hybrid` adapter applies authorization before candidate retrieval,
then fuses four PostgreSQL lanes with reciprocal-rank fusion: compact exact
matching for joined terms, trigram tolerance, weighted full-text metadata and
passages, and cosine distance over a local multilingual E5 projection. The
embedding model and its tokenizer are pinned image artifacts; queries and paper
text do not leave Scholens for semantic retrieval. `postgres_fts` remains an
explicit lexical-only degradation backend, and semantic runtime failure falls
back within the hybrid adapter without failing the search request.

The query planner keeps numeric-only input and ambiguous short input below
three compact characters out of fuzzy, full-text, passage, and semantic lanes;
two CJK characters are sufficient to enable hybrid retrieval. Those strict
queries match only complete title, author, or keyword tokens,
normalized DOI equality, and an exact publication year for four digits. Hybrid
trigram candidates require similarity `0.12`. If any exact metadata result
exists, semantic retrieval may rerank only the lexical result set and cannot
expand it. Otherwise, a semantic-only result must have cosine distance at most
`0.20`, be within `0.04` of the best semantic candidate, and is capped with all
other semantic-only results at 20. These are conservative acceptance guardrails
bound to the pinned embedding-model revision, not a claim of completed relevance
calibration. Loosening them requires the fixed evaluation set called for by ADR
0030. The policy lives with the paper-search adapter rather than the
provider-neutral embedding package. Response totals and `search_mode` describe
the accepted result set, not every vector candidate considered. Result snippets
come only from full-text-matching passages; the same PostgreSQL query produces a
ranked headline before it is projected as bounded plain text, so stemming does
not discard a valid passage. An unmatched paper never receives the beginning of
raw parser Markdown as a fallback snippet.

Query normalization applies NFKC to user input, but the current generated
compact metadata projection is lowercased and punctuation-stripped without
NFKC. Compatibility-form characters already stored in paper metadata are not
therefore guaranteed to match their ASCII equivalents; repairing that side of
the comparison requires an expand–backfill–switch projection migration.
Metadata expressions and the explicit trigram similarity threshold can also
require a scan at the current product scale. Before increasing the 5,000-paper
account limit or applying this adapter to a materially larger corpus, the owner
must add a production-shaped `EXPLAIN ANALYZE` latency gate and choose an
index-backed candidate strategy; changing to PostgreSQL's `%` operator without
controlling its session threshold would silently change recall.

`Document.search_text_compact` and `DocumentSearchEmbedding` are derived search
projections. The latter is keyed by document and model revision and carries a
digest of the bounded title/keywords/summary/abstract source. PDF completion
may upsert the current embedding, while the bounded, repeatable
`maintenance backfill-search-embeddings` command finds missing or stale digests
for existing documents. Retrieval responses report their active mode and
semantic coverage; raw user queries are not written to analytics telemetry.
`PAPER_SEARCH_BACKEND` is validated at startup. HTTP, Agent, and MCP consumers
continue to depend only on the application port and public search contract.

The search collection named `library` is a computed access view, not a synonym
for `LibraryPaper` membership. It contains the user's personal-library papers
plus papers available through Projects they own or collaborate on. Access is
re-evaluated for each operation, and the outer `Document` query keeps papers
that are reachable through several paths unique. Personal-library listing,
tags, storage accounting, and ingestion ownership continue to use
`LibraryPaper`; no Project paper is copied into the personal library.

Personal status and tag filters are applied to an actor-scoped `LibraryPaper`
projection before search totals and page slicing. Search results expose the
same optional personal status, tags, and last-access timestamp used by Library
and Project Papers without changing hybrid ranking, thresholds, or retrieval
lanes. Tags for a result page are loaded in bulk rather than one query per row.

## Library collection

The Library exposes two deliberately different collections:

- Papers are personal `LibraryPaper` memberships. Search, tag OR-filtering,
  status OR-filtering, stable keyset sorting (including last access), removal,
  download, and ingestion operate on that
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

`GET|PUT /api/v1/me/paper-list-preferences` owns the ordered, duplicate-free
visible paper columns, bounded per-column widths, and shared preview width/open
state. Missing storage returns the canonical default columns and layout sizes
with an open preview. Updates are user-isolated; older callers may omit the
additive size fields, while supplied size entries merge into the stored layout.
The preference does not persist browse filters or sorting.

`GET /api/v1/library/summary` returns successful Paper and Output counts plus
the number of current ingestion lifecycles and failed ingestions that require
attention. Both list endpoints use signed Previous/Next keyset cursors bound
to user, collection, filters, and sort; page size is a caller preference and
never binds the cursor. Paper sources enter through the discriminated
`POST /api/v1/paper-ingestions/sources` contract (`doi`, `arxiv`, or direct PDF
`url`); URL resolution and PDF validation remain server-owned. Failed jobs are
retried by creating a new durable job from the persisted source, never by
mutating the failed history row.

PDF uploads and source imports share one atomic acceptance boundary. A local or
browser client first creates a 24-hour `PaperUploadSession` using only a plain
filename, exact byte count, SHA-256, optional Project, and the
`add_to_library` intent (defaults to true). Server returns a
15-minute S3 PUT URL signed for PDF content type and checksum. The client sends
bytes directly to object storage; Server credentials and Scholens Access Keys
are never attached to that request. Ingestion claims the session for five
minutes with a generation-specific lease token, rechecks Project access and the
`add_to_library` intent, verifies stored size and the S3 checksum, downloads
and hashes the bounded bytes again, and then enters the canonical byte-ingestion
path. A stale worker cannot
consume or release a newer claim. Success consumes the session and removes its
staging object; validation failure makes it non-reusable, transient failure
releases it for retry, bounded request-time cleanup removes expired database
rows, and bucket lifecycle removes abandoned staging objects.

The official local stdio connector obtains filesystem roots from the MCP host
or explicit `--allowed-root` values. It resolves real paths, rejects ambiguous
relative names and symlink escapes, requires a regular `.pdf` with a PDF
signature and a maximum size of 30 MB, and sends the remote service only the
plain filename, size, checksum, and bytes. It uses separate HTTP clients for
authenticated MCP and unauthenticated object upload, preventing credential
forwarding. Both URLs require HTTPS except for explicit loopback development;
redirects and embedded URL credentials are rejected. If transfer completes but
the ingestion response is uncertain, the
bridge returns the original upload UUID and exact `ingest_paper` arguments so
the Agent replays only that final step without changing the idempotency
identity. No inbound port or public client IP is required.

After staging, a `202`
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
/api/v1/paper-ingestions/{job_id}` cancels a pending or running job and dismisses
a failed ingestion from Library. Dismissal retains the immutable failed Job and
error code, prevents another retry from its source, and excludes the reservation
from Library rows and attention counts; cancelled jobs reject replay and ignore
late worker callbacks. Both outcomes schedule reference-safe Document cleanup
when this ingestion created the final membership. The worker reports bounded
lifecycle stages and heartbeats, while the Server owns terminal timeout/failure
policy.
Production callback authorities fail closed at process startup and Jobs pins
signed internal paths to its own validated Server base. A published PDF task
that never claims its durable job is replaced once after the configured
one-hour bound; the source reservation is superseded without removing an
existing membership or charging storage/reference quota again. A second lost
claim becomes the retryable `paper_ingestion_claim_failed` terminal state.
Ingestion attaches memberships atomically: the uploader's personal Library
membership is the default even for Project-targeted uploads, and the Project
membership is an independent idempotent association. `add_to_library=false`
(requires a Project) keeps a paper Project-only. Failure and cancellation
compensation removes only the membership(s) the job actually created, and a
retry inherits the original job's `add_to_library` intent.

PDF completion persists extracted metadata, generated summary, and summary
citations on the canonical `Document`. It rejects a successful worker result
whose `s3_object_key` does not match the Document's canonical source key,
failing the job with `job_result_key_mismatch` instead of persisting content.
Jobs parser fallback and Server repair adoption share one service-neutral PDF
text-quality contract from `scholens_job_contracts`: the Unicode replacement
marker and warning, three-attempt ceiling, 80–125% substantive-content ratio,
and 80% ordered bounded-evidence threshold have no per-service copies. Jobs adapts the
decision to `ParsedDocument`; Server adapts it to canonical-content and
annotation-reanchoring workflow state. The signed callback transport has one
Jobs/Server-owned 64 MiB wire-body ceiling, repair candidates have a 40 MiB
UTF-8 ceiling, encoded page offsets have a 2 MiB ceiling, and
reanchoring rejects work above explicit thread, cumulative-quote, or scan
budgets without replacing canonical text. Repair Job JSONB retains bounded
audit evidence rather than candidate bodies. Rejected candidates, superseded
parser artifacts, and every repair namespace found by final Document GC are
deleted through the transactional storage-deletion outbox. That outbox validates
the generated `documents/` and `research/audio/` namespaces before the owning
transaction commits and consumes strictly increasing, caller-owned key streams
without retaining prior batches. It rejects duplicate or out-of-order keys
across batch boundaries and creates deterministic batches bounded to 100 keys
and 64 KiB of compact key JSON. Batch idempotency is bound to its ordinal and
SHA-256 key digest. Jobs repeats the shared key and batch validation before
claim or S3 I/O, while Server verifies that each signed completion count equals
the exact persisted batch. Project deletion confirmation computes bounded
counts and revision digests, then re-reads created cleanup Job IDs in bounded
origin-operation pages so every Job is journaled without materializing the
Project's associations, storage keys, or audit entries.
It does not synthesize a paper-scoped conversation or a fake user turn.
Starting a conversation about a paper is an explicit user operation and the
conversation references that existing Document-owned context.

## First-party research activity

The research-activity capability is delivered with the additive contract and
schema introduced by [ADR 0039](../decisions/0039-first-party-research-activity-ledger.md).
It does not backfill reading duration from `LibraryPaper.last_accessed_at` or
from Project actions that predate collection. Insight responses expose
`reading_data_since` and `activity_history_complete_since` so clients can
distinguish an empty period from unavailable historical evidence.

The public HTTP surface is:

- `GET|PUT /api/v1/me/reading-activity-preferences` for the independent
  recording and anonymous-Project-contribution preferences;
- `POST /api/v1/papers/{document_id}/reading-sessions` to open an owner-scoped
  session after paper and optional Project-context authorization;
- `PUT /api/v1/reading-sessions/{session_id}` to submit cumulative visible,
  active-estimate, page, and normalized-region evidence;
- `GET /api/v1/papers/{document_id}/insights`,
  `GET /api/v1/projects/{project_id}/insights`, and
  `GET /api/v1/me/research-insights` for paper, private-versus-team Project,
  and personal period projections;
- `GET /api/v1/projects/{project_id}/activity` for the authorized Project-fact
  feed;
- `GET /api/v1/me/reading-activity/export?format=json|csv` for an actor-owned
  portable export;
- `DELETE /api/v1/reading-sessions/{session_id}`,
  `DELETE /api/v1/papers/{document_id}/reading-activity`,
  `DELETE /api/v1/projects/{project_id}/me/reading-activity`, and
  `DELETE /api/v1/me/reading-activity` for session, paper, Project-attribution,
  and complete scopes.

Preferences default to `recording_enabled=true` and
`contribute_anonymous_project_aggregates=true`. Turning off recording prevents
the Web from opening another behavioral session; turning off Project
contribution prevents future Project-attributed rollups. Neither mutation
deletes existing history. Deleting a Project contribution preserves the same
user's personal evidence, while paper, complete-history, Project, Document, and
account deletion follow their owning cascade.

The first measurement definition is `active-reading-v1`. Web admits bounded
five-second slices only while Reader is foreground-visible and focused, treats
interaction older than 120 seconds as idle for the active estimate, and flushes
cumulative evidence at most every 30 seconds and at lifecycle boundaries.
Server rejects a decrease, a duration outside the bounded session contract, an
active value greater than visible, an unauthorized Project attribution, or a
page/region outside the Document bounds. Substantive coverage requires 15
active-estimate seconds on a page, and the vertical page distribution uses 20
normalized regions. The API names and copy retain estimate semantics; no field
claims gaze, attention, comprehension, or productivity.

Fine session-page trajectory rows have a 90-day retention ceiling. Coarse
sessions and personal page/hour rollups remain until user or account deletion;
Project-attributed page/hour rollups remain until contribution, source,
Project, or account deletion. Maintenance removes expired detail without
discarding the coarse personal trend and marks the owning session as purged. A
request to delete that one old session returns a stable conflict because its
deltas can no longer be reversed exactly; paper, Project-contribution, and
complete-history deletion remain exact. Export and every deletion authorize
the actor before retrieval or mutation.

Project insight returns the current actor's private contribution independently
from its team projection. Team reading statistics are suppressed unless the
selected period contains at least three contributors, and returned team time is
rounded to five-minute units. There is no member filter, exact team session
boundary, per-member series, or leaderboard. Project activity is computed from
the canonical Project Paper, Project-audience Research Item and annotation
comment, and Project collaborator records. There is no copied
`project_activity_facts` table.

PostHog and OpenTelemetry are operationally separate and are not composed as an
activity repository. Logs, metrics, traces, the Operation Journal, Redis, and
job envelopes receive no session path, page payload, selected text, or exported
history. Low-cardinality endpoint outcome and latency telemetry remains
permitted.

## Billing usage projection

`GET /api/v1/billing/usage` returns the selected inclusive date-only period,
the effective plan, current resource usage, and plan limits. Storage accounting
is persisted and returned in KiB; public fields therefore use the explicit
`knowledge_base_size_kb` and `knowledge_base_size_remaining_kb` names. Clients
must convert those quantities from KiB rather than treating them as bytes.
`period_end` is the inclusive final day of the selected window, not a timestamp
or the next reset instant.

This is the only mounted billing HTTP route in the current production release.
Checkout, customer portal, subscription refresh/mutation, and Stripe webhook
code remains dormant and is not composed into FastAPI; production therefore
injects no Stripe or PostHog configuration. Researcher access is granted and
revoked only through the audited private CLI. Re-enabling public charging
requires a later review that restores the provider boundary, runtime secrets,
edge scope, and end-to-end tests together.

Account paper and storage usage is the unique union of completed Documents in
the personal Library and Projects owned by that account. A repeated Document
therefore adds no account cost until its final owned reference disappears.
Project paper limits remain membership counts, and collaborators reserve quota
against the Project owner. When a collaborator uploads into another user's
Project with `add_to_library=true`, the uploader's own account reserves one
personal Library slot; an owner uploading to their own Project is never
double-charged because of the account-unique union. Account advisory locks and
durable upload reservations serialize concurrent additions, including Project
creation and ownership transfer. Transfer locks both account quota namespaces
in stable user-ID order and recomputes both owners' completed and active
unique-document views before committing; an already-owned Document may reserve
zero account units while still reserving one Project slot. Project ownership
transfer derives each target upload's post-transfer Project and Library billing
roles from its uploader and the new owner, then reprices both accounts without
double-charging a digest.
Paid subscriptions, product entitlements, and capacity writes share one
billing-owned PostgreSQL bigint advisory key. The key is a stable BLAKE2b-64
digest of a versioned account-resource namespace plus the complete bigint user
ID. Theoretical hash collisions only serialize unrelated accounts
conservatively; they cannot bypass capacity checks. This one-key space is
distinct from the administrator roster's two-key namespace.

Effective entitlements combine paid `subscriptions`, product-owned
`account_plan_grants`, and active `account_quota_overrides`. A paid Researcher
and a granted Researcher are evaluated independently, numerical overrides
replace only their named limit, and expired/revoked records are ignored. This
resolution is shared by HTTP usage, upload/project checks, Zotero sync, and AI
Token Credit enforcement; the public `plan/limits/usage` shape is unchanged.

Operator writes use the same application capabilities and Unit of Work as HTTP
commands. CLI provenance is recorded as `CliOrigin(command_name,
invocation_id)` in the append-only Operation Journal. SQLAdmin views are
read-only; no public administrator API exists for grants, quota overrides,
subscription mutation, token resets, or arbitrary job state changes.
Administrator bootstrap and reductions serialize through a dedicated
transaction advisory lock before re-reading the available-admin roster.
Every privileged operator command takes that same roster lock, then locks and
re-reads its actor's AuthUser and UserProfile rows before authorization. This
keeps the lock order consistent with revoke/block and holds the live admin fact
through the mutation transaction.
Free-text entitlement reasons live on entitlement records. Identity
admin/block, development bootstrap, and passage-maintenance commands do not
accept prose with no persistence destination; they retain only their structured
Journal safe projection plus explicit confirmation where a write occurs.

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
