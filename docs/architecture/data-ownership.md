# SanchezCloud identity and Scholens data ownership

The canonical cross-product identity rules live in the
[SanchezCloud Identity engineering handbook](https://github.com/EricSanchezok/sanchezcloud-identity/blob/main/docs/README.md).
This document defines the Scholens-specific database and deployment contract.

## Storage ownership

| Owner                   | Responsibilities                                                                                                                                                                                | PostgreSQL ownership                                                                                                            | Explicitly excluded                                                      |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `sanchezcloud-identity` | Email identity, passwords, verification, global account status, lockout, public Account ID, shared avatar references, connected clients, security events, audience tokens, and refresh families | `auth.users`, `auth.refresh_tokens`, `auth.user_clients`, `auth.user_avatars`, `auth.security_events`, `auth.schema_migrations` | Product roles, blocks, subscriptions, quotas, usage, documents, projects |
| Scholens                | Documents, projects, collaboration, product profile/admin/block state, paid subscriptions, product plan grants, quota overrides, integration connections, and usage                             | `scholens.*` including `scholens.schema_migrations`                                                                             | Identity migrations, Scholight state, and Scholight Zilliz collections   |

Both schemas share the `sanchezcloud` database but have independent owners and migration
ledgers. `public` contains no application tables. Scholens rows may reference the internal
`auth.users.id`; they must not use a public Account ID as a relational key or write another
product schema.

## Identity integration

- `client_id=scholens`, the JWT secret, audience, and `scholens_refresh` cookie are stable and
  unique to Scholens.
- Access tokens stay in browser memory. Production refresh cookies are host-only, `Secure`,
  `HttpOnly`, and `SameSite=Strict`.
- Identity managers own password, token, and refresh-session behavior. Scholens must not query
  or mutate `auth.refresh_tokens` directly.
- Account Center remains the only avatar management surface. The Scholens API may read
  `auth.user_avatars` through the pinned Identity SDK solely to mint short-lived private GET
  views for already-authorized users; it never stores an avatar reference in `scholens.*`,
  writes the Identity table, proxies image bytes, or exposes the view through MCP, jobs, or
  the shared Actor.
- The explicit local-only `dev seed-test-account` fixture delegates identity
  creation, verification, password hashing/reset, and session revocation to the
  pinned Identity SDK. It accepts only synthetic addresses against the exact
  shared-local runtime database and is never invoked by application startup.
- Product profiles, roles, administrators, blocks, subscriptions, quota, and usage remain in
  `scholens.*`.
- `subscriptions` records payment state only. Internal Researcher access lives
  in `account_plan_grants`, and temporary numerical test limits live in
  `account_quota_overrides`; neither table mutates or impersonates Stripe. The
  current production release does not expose a payment mutation or webhook
  route, so only audited private CLI grants create new Researcher access.

## Project invitation and email ownership

`scholens.project_invitations` owns both collaboration intent and product-email
delivery state. Creating an invitation writes its `pending` state in the same
Server transaction; short-lived leases, attempt count, next-attempt time,
sanitized failure code, and delivered time remain Scholens product data. The
Server may claim and recover those leases across API replicas, but Aliyun does
not own a queue or a product status.

Invitation bearer tokens are not stored. A deployment-owned
`PROJECT_INVITATION_TOKEN_SECRET` signs only invitation ID and revision. Normal
delivery retries reuse a revision; an explicit resend increments it so the old
link becomes invalid. Accepting still revalidates expiry, recipient identity,
and the inviter's current authority. Identity verification and password-reset
templates remain owned by `sanchezcloud-identity`; both interfaces may share one
Aliyun DirectMail account without sharing application contracts or tables.
Database checks constrain token revisions, delivery states, attempts, and lease
pairs so corrupted rows cannot silently enter the dispatcher.

## Database roles and migration order

- `auth_migrator` owns only `auth` and is used by the protected Identity workflow.
- `scholens_migrator` owns only `scholens`, reads the Identity schema ledger, and may reference
  `auth.users` during product migrations.
- `scholens_app` owns nothing. It receives minimum Identity core DML, the existing append-only
  security-event capability, read-only shared-avatar references, and Scholens runtime DML. It
  cannot write avatar references or migration ledgers, execute DDL, alter another schema, or
  update/delete operation-journal entries.

`deploy/ecs/database-bootstrap.sql` is the reviewed grant contract. It does not create login
roles or persist credentials. The required order is:

1. infrastructure creates roles and runs the bootstrap to create owned schemas;
2. the protected Identity workflow migrates `auth.*` as `auth_migrator`;
3. the database owner reapplies grants;
4. Scholens validates the Identity version, audits the exact read-only shared-avatar
   runtime grant, and migrates `scholens.*` as `scholens_migrator`;
5. the database owner reapplies runtime grants;
6. CI audits `scholens_app` with the Identity `product-runtime` profile and separately verifies
   the Scholens avatar-read extension, Scholens DML, append-only journal behavior, and
   cross-schema denials.

A Scholens deployment never bundles or executes Identity migrations. Identity
compatibility remains an independent required check before its schema version
or the Scholens dependency may advance.

## Conversation storage

Scholens owns conversation state entirely inside `scholens.*`. A
`conversation_turns` row is an immutable user request and owns one or more
`conversation_responses`. Parent and selected-child links form persistent
prompt branches; the Conversation's selected root and the selected child at
each depth define the authoritative active path. A monotonic path revision keeps
pagination from combining different selections. The turn's selected response
is the sole answer used for model history on that path. References, research
items, artifacts, worklog trace, total duration, and safe terminal failure
metadata belong to a concrete response ID. Raw provider bodies and exceptions
do not. Follow-up suggestions belong to the turn because retries and
selected response variants share the same next-question context.

Historical prompt edits read the source turn's context as an immutable snapshot;
that preparation does not own a write. After quota, access, context, rate, and
capacity checks pass, one Server transaction restores the Conversation's current
paper context, inserts the new sibling and running response, switches the selected
path, and increments `path_revision`. Those aggregate fields therefore never
describe a branch that the Server has not durably accepted. The same transaction
creates a `conversation_generate` DurableJob and outbox dispatch whose ID equals
the Response ID. The job owns delivery and lease state only; it never owns the
answer or selects the active branch. For a first prompt, that same transaction
may insert the client-identified Conversation before its root Turn; no empty
Conversation or partial first generation becomes externally accepted.

A turn also owns its typed paper-context snapshot and Reader context. A
`paper_selection` captures the
authorized Document, selected text, one-based page, and normalized PDF anchor;
an `annotation_thread` captures an authorized Research Item reference.
Arbitrary reference dictionaries and parallel annotation-ID fields are not
persisted.

Only the active leaf may expose its running response and multiple terminal
response variants. Its latest
completed, failed, or cancelled attempt remains selected so duration and retry
position survive refresh; stable failure classification and diagnostic IDs are
product data while raw failure details are not. Creating
a normal child removes unselected response variants from its parent and clears
its no-longer-visible suggestions. Editing creates a sibling without deleting
the source or either subtree; selecting a prompt branch restores its stored
selected suffix and reauthorizes the selected leaf's paper context. No Identity,
Scholight, or Jobs schema owns or selects a conversation response; callbacks may
update Scholens-owned artifacts only through the Server's verified application
boundary.

## Library storage and projections

`Document` owns canonical paper metadata, generated summary and summary
citations, and source-object identity. A PDF-processing callback updates those
document-owned fields; ingestion never creates a Conversation, Turn, or
Response. Paper-scoped conversations exist only after an explicit user action
and consume the Document as context rather than owning its canonical summary.
`LibraryPaper` owns one user's personal membership, metadata overrides, tags,
status, sharing state, and last-access time. Removing that membership never
implies deleting a `Document`: Project references and other users' memberships
remain authoritative, and orphan cleanup is scheduled outside the request
transaction. The same removal transaction deletes annotation threads created
by that user with personal audience and the removed Document as their target.
It never deletes Project-audience threads or another user's annotations.

`PaperTag` owns a user-scoped label name. Renaming or deleting it is authorized
against that owner; deletion cascades only its Library Paper assignments.
Library Paper tag edits are exact-set replacements, so clearing the final tag
does not require a separate compatibility endpoint.

`PaperListPreference` owns one user's ordered visible-column set, bounded
per-column widths, paper-details-preview width, and preview disclosure. It is
Scholens account data keyed by the auth user ID; it does not move ownership into
the `auth` schema. Library, Project Papers, and their search projections read
the same preference, while sort and filter state remain URL-owned browser state.
Project and search personal metadata is
always projected from an actor-scoped `LibraryPaper` join. A Project-only
Document returns no personal status, tags, or last-access time, and another
user's private Library metadata is never a fallback.

`PaperUploadSession` owns temporary direct-upload intent before a Document
exists: actor, optional Project, plain filename, declared size and SHA-256,
`add_to_library` intent, private staging object key, expiry, and ingestion
lease state. It never stores a client filesystem path. A consumed session
cannot be reused, and abandoned objects are also bounded by the content bucket
lifecycle. The canonical Document and Library/Project memberships remain owned
by the normal ingestion transaction; staging is not a second paper record.

Ingestion attaches memberships atomically: the uploader's personal Library
membership is the default for every upload (including Project-targeted ones),
and the Project membership is an independent idempotent association.
`UploadReservation` records each side's creation separately
(`reference_created_library`, `reference_created_project`) so failure and
cancellation compensation deletes only the membership this job created, never
a pre-existing membership. The library-side billing owner and reserved
capacity are stored on the reservation alongside the Project owner's side.
During the additive rollout, nullable `add_to_library` distinguishes rows
written by the previous application, and the legacy `reference_created` flag
is retained and dual-written; their removal requires a later contract release.

`ActionConfirmation` owns only short-lived authorization to perform one risky
action. It stores a token hash, actor and credential binding, action and
argument digests, live-state fingerprint, bounded impact, expiry, and consumed
time. It does not own the target Project, paper, membership, share, invitation,
job, or annotation. Target services remain authoritative and are re-read before
the confirmation is consumed.

Library Outputs do not introduce another persistence model. They are a
permission-filtered read projection of Scholens-owned `ResearchItem` rows and
their existing kind-specific payload tables. Audience access is resolved by the
Server. The Web receives source audience/title as projection metadata and must
not infer ownership by composing unrelated APIs.

Research-item audience and annotation target are separate axes. Audience is
`personal`, `document`, or `project` with the corresponding audience ID, while
an annotation thread independently owns a required `target_document_id`.
Annotations allow only personal and Project audiences: a personal thread is
creator-only and a Project thread is visible only to current members of that
specific Project. A paper appearing in several Projects never makes one
Project's annotation visible in another. Citation, audio-overview, and data-
table outputs retain document or Project audience as their producer requires.

Annotation-thread positions are canonical Research data. PDF selections use
one-based pages and normalized rectangles; parsed-text selections use validated
start/end offsets with an optional page projection. A thread owns one color,
immutable audience and zero or more chronological comments. Comments inherit
the thread audience and own only their content and author. Threads do not
support recursive comment trees or audience mutation.

Translation preferences are user-owned Scholens data and are independent from
the interface locale. Translation results are document-derived Scholens data:
they own the translated text plus hashed request identity, language, prompt,
and AI-profile revisions. They never own or duplicate raw selection source
text. Deleting the source Document cascades its derived translation results.
Redis does not own completed translations; it owns only short-lived capacity
and single-flight coordination.

## Integration credentials

`IntegrationConnection` is user-owned Scholens data. It records one provider,
enabled state, encrypted credential payload, non-secret display metadata,
provider configuration, credential revision, verification outcome, and
lifecycle timestamps. The Server is the sole persistence and decryption
authority. Public projections never return a stored secret, and Jobs has no
process-level MinerU token or Zotero API key. Zotero's OAuth-issued API key is
the long-lived credential in this same store; its request-token secret is
encrypted separately in a short-lived `ZoteroOAuthPending` row that is consumed
once. Neither credential belongs to the `auth` schema.

A DurableJob stores the owning user, but neither the plaintext credential nor a
credential revision. After the worker has claimed that eligible job, it may
fetch the user's currently enabled MinerU token through the signed internal
API. That response is scoped to the exact job, owner, operation, provider, and
current connection revision; the plaintext exists only at the provider-call
boundary and must not enter logs, exceptions, callbacks, task payloads, or
operation provenance. Provider outcomes sent back to Server carry the fetched
revision, so a delayed failure is ignored after the user replaces the
connection.

Disconnecting or replacing a connection does not rewrite immutable job
history. A retry creates or resumes a new eligible attempt against the current
credential revision. Later schema changes preserve this data through the
production evolution policy; temporary overlap remains in the owning
persistence or transport adapter and never creates a second credential
authority.

`ZoteroOperation` owns one accepted import or sync request, its idempotency
identity, summary counts, safe terminal code, and ordered item results.
Its DurableJob also owns a short-lived callback lease distinct from the worker
lease. Server must atomically acquire that lease before applying provider
outcomes; terminal, cancelled, concurrent, and replayed callbacks own no product
side effects. The claim is renewable while the callback consumes a batch one
PDF at a time. Server owns the 12-minute processing bound and 30-second
heartbeat, Jobs waits up to 13 minutes, and the claim remains exclusive for 15
minutes. These values are a shared service-neutral contract, not queue policy.
The same package owns the 12 MiB exact-body ceiling and the 4 MiB automatic-import
reserve. Jobs owns incremental result admission and immediate cleanup of staging
that was never handed to Server; Server owns defensive validation before mutation.
Sync targets omitted because the annotation projection is full have no attempted
state change, and automatic-import cursor ownership never advances beyond the
returned resolved prefix.
`ZoteroImportedItem` links the user's Zotero item and optional attachment to
the canonical Document and paper-ingestion job. It separately records
`last_sync_attempted_at`, successful `last_synced_at`, annotation-source status,
and a stable last error. Failed attempts advance only the fairness marker;
provider-confirmed missing items or attachments become `source_unavailable`
without deleting the local Document or existing annotations. The Integration
Connection
configuration owns automatic-import preference and Zotero library-version
checkpoints plus the bounded secondary page position. Enabling automatic
import records the current version; later automatic runs advance only through
the contiguous accepted or permanently skipped prefix of a signed result.
Transient and quota failures retain their position for retry. Zotero
annotation keys live on the resulting Scholens annotation threads and make
append-only application idempotent.

Disconnecting Zotero removes future credential availability and scheduled
access. It does not delete `ZoteroOperation`, `ZoteroImportedItem`, Documents,
Library memberships, or annotation threads already created through the
integration. Jobs may retrieve the current Zotero API key only for a claimed,
owner- and operation-scoped Zotero job. The key and revision follow the same
payload, logging, callback, and stale-failure restrictions as MinerU.

Jobs owns private `zotero-imports/` staging until a delivery has a definite
Server outcome. It may delete staging after controlled provider failure or
cooperative cancellation before delivery. Once delivery begins, Server may be
reading the object; an HTTP timeout or connection failure is therefore
ambiguous and preserves staging. Server deletes it after a definite claimed
result, and the bucket's two-day lifecycle owns crash and ambiguous-delivery
cleanup.

Server owns canonical `documents/{sha256}/source.pdf` objects. Callback import
holds only one downloaded PDF at a time. If cancellation interrupts a
thread-backed canonical upload, Server tracks the still-running task until it
settles without extending the callback processing bound. If cancellation wins
before the matching Document transaction, the content-addressed object is
retry-safe but may be unreferenced. Only reference-aware Server
document-storage reconciliation may reclaim it; neither Jobs nor the Zotero
staging cleanup path may delete canonical document content.

`DocumentReflow`, its ordered `DocumentReflowBlock` rows, and
`DocumentReflowAsset` rows are derived from the Document's canonical parser
Markdown and original PDF. Blocks preserve the exact source Markdown while a
separate render field may contain evidence-validated presentation repairs.
Every block and asset retains a page and normalized source rectangle when the
PDF provides one. Server owns asset metadata and private object keys; clients
receive only authorized short-lived URLs. They never replace the PDF, parser
artifact, metadata, or processing status. A reflow references its current
DurableJob; failed attempts remain immutable Jobs history, successful retries
replace old blocks and assets, and deleting the Document cascades the derived
records and schedules their physical objects for deletion.

Paper ingestion jobs retain immutable failure history. A retry creates a new
`DurableJob` referencing the persisted PDF source and original Project context;
it does not reset or overwrite the failed job.

An ingestion operation owns its reservation, source identity, DurableJob, and
dispatch outbox record. Server commits those records together before returning
acceptance. Jobs may report progress or a terminal result only through the
signed callback boundary; it never creates Library membership directly.
Cancellation is a terminal Server decision. Storage cleanup is scheduled after
the transaction, and any callback arriving after cancellation is an idempotent
no-op rather than a second state authority.
