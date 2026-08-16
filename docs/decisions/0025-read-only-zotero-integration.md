# 0025 — Read-only Zotero integration across Server and Jobs

Status: Accepted
Date: 2026-08-16
Owners: Scholens
Refines: [ADR 0019](./0019-user-owned-integration-credentials.md)

## Problem

The previous Zotero implementation stored a separate plaintext connection and
performed provider work synchronously. Its OAuth request-token secret lacked a
clear replay boundary, remote browsing and import could hold request resources,
and a Celery task could not prove that its credential still belonged to the
current user connection. Legacy routes also blurred manual annotation sync,
automatic annotation sync, and automatic paper import.

Scholens needs a production-safe connection in the replacement Web while the
product is still pre-release. It must support Basic and Researcher behavior,
partial batches, quotas, cancellation, and provider rate limits without making
Jobs a credential or product-data authority. The first release must remain
one-way and personal-library-only.

## Decision

Zotero is the `oauth` provider in the unified `IntegrationConnection` store and
the `reference_manager` category in its public inventory. The OAuth-issued API
key is encrypted by Server with the existing connection mechanism. The OAuth
request-token secret is encrypted in a short-lived row, bound to an authenticated
user, validated local return path, and `manage` or `import` intent, and consumed
once. Callback verification requires personal-library, files, and notes read
access, rejects write and Group Library access, and redirects only to the
original in-product path with a stable result code.

Zotero browsing remains a Server-owned external-I/O workflow with provider-aware
pagination and signed query-bound cursors. Import and sync write no remote data
inside the HTTP request. Their accepted transaction creates a
`ZoteroOperation`, DurableJob, and outbox dispatch and returns `202`. A worker
may retrieve the current credential only after claiming that exact owner and
operation. Task payloads, callbacks, logs, exceptions, journals, and telemetry
remain secret-free; callbacks carry the fetched revision, and only a failure
matching the current revision may invalidate the connection.

Jobs performs read-only item, file, and annotation requests, validates PDFs,
and uploads accepted sources to temporary private storage. Its signed item
callbacks ask Server to create the standard paper-ingestion lifecycle or apply
annotations idempotently by Zotero annotation key. Operation state supports
partial success, retryable rate limits, cooperative cancellation, and replayed
callbacks. The connection row serializes acceptance so a user has only one
active Zotero operation, and status exposes its kind and ID for refresh-safe
recovery without exposing a generic job payload.

Manual sync applies new annotations only to papers already imported from
Zotero. Researcher scheduled sync performs the same annotation work. Automatic
paper import is a distinct, explicit, default-off Researcher preference. When
enabled, Server records the current Zotero library version. Each scheduled run
reads a bounded 50-item page and persists a secondary position only through the
contiguous accepted/permanent-skip prefix; transient downloads, rate limits,
and quota failures are retried instead of being skipped. Losing Researcher
access pauses automatic work without
clearing the preference. Disconnecting revokes future access but retains
imported papers, annotations, operations, and audit history.

The integration supports only personal-library `journalArticle`,
`conferencePaper`, and `preprint` items. It never writes to Zotero, synchronizes
deletions or overwrites, or accesses Group Libraries.

## Alternatives considered

- Keep a standalone plaintext `zotero_connections` table. Rejected because it
  creates a second credential authority and cannot share revision-bound job
  isolation.
- Put the Zotero API key in Celery messages or Jobs environment variables.
  Rejected because queues, retries, task inspection, and worker processes would
  become long-lived secret stores without an owner/operation proof.
- Complete import synchronously in Server. Rejected because provider paging,
  PDF downloads, S3 uploads, and paper processing exceed a reliable HTTP
  transaction boundary and cannot represent partial completion cleanly.
- Treat Sync now as a full library mirror. Rejected because a manual annotation
  action must not silently consume paper quota or import new research.
- Enable future-paper import by scanning the existing library. Rejected because
  the user's opt-in is prospective and Zotero version checkpoints provide a
  deterministic incremental boundary.
- Search Group Libraries or write annotations back to Zotero. Rejected because
  group authorization and bidirectional conflict/deletion semantics require a
  different product and privacy contract.
- Preserve the legacy routes and table during migration. Rejected because
  Scholens is pre-release and reset-first convergence avoids dual authorities
  without touching the independently owned `auth` schema.

## Consequences

Server owns OAuth security, encryption, connection revision, eligibility,
quotas, operation persistence, checkpoints, standard ingestion, and annotation
application. Jobs owns short-lived provider I/O, PDF safety, incremental
pagination, retry classification, and cooperative cancellation. Web owns
connection management, library selection, asynchronous operation feedback, and
localized recovery states through generated API types.

Automatic synchronization still requires an external scheduler trigger, and a
real deployment still requires a registered Zotero OAuth application and
Server-side client credentials. This decision defines their contract but does
not enable scheduler or deployment configuration.

## Validation

Server tests cover OAuth expiry/replay/return paths, encrypted secrets,
permission verification, cursor binding, 100-item pagination, quota,
idempotency, checkpoints, entitlement pause/resume, stale revisions,
cancellation, and retained data. Jobs tests cover success, partial failure,
rate limiting, credential rotation, retry, cancellation, PDF safety, version
pagination, and secret-free logging. Web unit and Storybook tests cover OAuth
return, connection management, browsing, retained selection across pages,
quota, batch progress, partial completion, keyboard behavior, narrow layouts,
themes, and English/Simplified Chinese states.
