# 0057 — Fenced durable result inbox

Status: Accepted
Date: 2026-09-27
Owners: Scholens Jobs and Server maintainers

## Problem

A worker callback currently waits for business persistence and, for some
operations, provider calls. Long responses can outlive the worker's HTTP timeout.
Replaying execution to repair delivery can repeat paid work. Process-local
state cannot arbitrate a stale worker after a lease takeover or Server restart.
Synchronous callback database and storage work also blocks the API event loop.

## Decision

Separate execution, receipt and application. PostgreSQL owns a monotonically
increasing execution generation and a durable inbox. Workers upload an immutable,
bounded content-addressed result and submit only its manifest. The receiving
transaction checks job scope and generation and durably transfers ownership to
the inbox. Artifact verification happens outside the transaction; the execution
fence, business write, and acknowledgement share one later transaction.

Use a nonce for each consumer reservation as well as the worker generation.
A process that lost its apply lease cannot acknowledge a replacement consumer's
work. One consumer thread per Server process bounds memory and transaction
concurrency. Provider work belongs in independent stages outside this apply
transaction. Parsed content can be made readable without AI metadata; omitted
metadata does not clear existing values.

Roll out consumer-first behind a disabled producer. Existing job payloads remain
accepted throughout drain and rollback. The owning jobs transport/persistence
adapters own this overlap; remove it only after the last legacy job is terminal
and the supported rollback release understands the replacement protocol.
Retirement also requires at least 90 days of compatibility and 30 consecutive
days without legacy traffic; removal is a later reviewed contract stage.

The worker transport persists a checkpoint pointer after uploading the hashed
result and before requesting a receipt. Recovery validates both and resubmits
the identical bytes under its new generation. Celery transport retries retain
the claim token; broker redelivery gets a new owner. A `checkpoint_only` job
cannot repeat an unknown paid outcome after takeover: it replays a known result
or records `provider_outcome_unknown`. Deterministic work may recompute when no
checkpoint exists. PDF workers accept an additive `delivery_protocol` argument;
`manifest-v1` always skips inline AI extraction. Existing envelopes retain their
legacy behavior at the transport adapter until staged producers are enabled.

Expired owners cannot resurrect leases, submit first results, or mutate source
materialization. Legacy claim/progress/complete/fail routes reject jobs with an
execution record. Source materialization validates the generation in the same
transaction as mutation. A nonterminal business handler cannot acknowledge an
inbox row. Exhausted application retries invoke the operation's failure handler,
domain compensation, and journal in the inbox rejection transaction; post-commit
concurrency release retains the normal owner policy. Apply transactions have a
five-second lock timeout and thirty-second statement timeout. Consumer logs
record bounded error classes without exception payloads.

Persist post-commit actions alongside the acknowledged/rejected result. An
independent nonce and leased reservation recover a Server killed after SQL
commit but before releasing user concurrency. External effects are at-least-once;
Redis member removal is idempotent and strict delivery propagates dependency
errors for bounded-backoff retry. Existing BYOK usage settlement remains a no-op;
this change does not create new usage accounting. Product analytics retains its
existing best-effort delivery semantics. Drain at most four effects between
result applications so neither backlog monopolizes the consumer.

Each fenced dispatch also creates a generation-zero cleanup effect. It becomes
eligible only seven days after a terminal job and after all that job's other
effects finish. Cleanup enumerates at most 100 keys per owned result/checkpoint
namespace per attempt; it accepts a UUID, never arbitrary object keys. Truncated
or failed deletion is retried idempotently. This covers rejected and orphaned
attempt artifacts, including cancellation without an accepted result.

## Alternatives considered

Increasing the callback timeout retains coupled failure domains and does not
solve request-loss ambiguity. A larger worker or unbounded callback thread pool
increases memory competition on the shared host. Retrying paid execution on any
callback error can duplicate provider work. Process-local deduplication cannot
survive restart or coordinate replicas.

## Consequences

The result namespace needs bounded retention, generation-aware replay, explicit
terminal failure handling, and reference-safe cleanup before producer activation.
Expanding schema and consumer support can deploy independently; activation and
removal require separate acceptance evidence. The current Server setting is
consumer-only and disabled by default.

## Validation

Real PostgreSQL tests exercise simultaneous claims, lost claim response,
reclaimed execution, repeated result acceptance, cancelled jobs, consumer
restart, atomic business-effect rollback and duplicate application. An N-1 job
still claims and completes on the expanded schema. Payload tests reject changed
bytes, digests, cross-job paths and oversize manifests before application.
Worker tests cover receipt loss, replay without paid work, lost claim identity,
corrupt checkpoints, generation loss, failed outcomes, bounded storage stream
closure, and readable PDF completion without metadata. PostgreSQL tests also
exercise expired leases before takeover, unfenced source mutation, nonterminal
handler acknowledgement, and compensation rollback.
Real PostgreSQL tests prove commit-before-effect restart recovery, lost effect
acknowledgement, stale effect-owner rejection, and cleanup retention/effect
dependencies. A Redis failure test proves strict delivery cannot acknowledge a
failed release; namespace tests prevent cleanup crossing a job boundary.

Paid stage adapters persist an external-effect intent before calling a provider.
Generation fencing alone is insufficient: a same-token retry after failed result
storage could otherwise call the provider twice. Replays first seek a complete
checkpoint; a surviving intent without a result produces an explicit unknown
outcome. Just-in-time credential and source-resolution requests carry and verify
the same generation, so an expired worker cannot continue acquiring dependencies.

## Independent readable-first stages

New producers are separately gated by `DOCUMENT_PIPELINE_ENABLED`, which requires
the inbox consumer. Extraction commits readable content and three independent
stage jobs. Deterministic indexing and bibliography may recover from checkpoints;
paid enrichment records intent before the external effect and fails closed on
unknown outcomes. All result writes verify current source/access, bibliography
also verifies citation identity, and enrichment only fills canonical gaps. This
keeps a provider outage or a manual edit from invalidating successful extraction.
Zotero imports retain authoritative metadata and omit automatic paid enrichment.
Legacy accepted envelopes keep their original behavior for the drain window.
