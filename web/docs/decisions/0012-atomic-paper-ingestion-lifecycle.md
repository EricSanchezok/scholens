# 0012 — Atomic paper-ingestion acceptance and cooperative cancellation

Status: Accepted
Date: 2026-08-12
Owners: Scholens

## Context

PDF upload and source import previously exposed several authorities: an upload
could return before its Library membership and durable job were committed,
processing appeared outside the Papers collection, the browser could not cancel
one item cleanly, and a worker/provider failure could leave a row running
indefinitely. A lost HTTP response also made it unsafe to decide whether a new
upload should use a new operation identity.

The product is pre-release. Preserving those intermediate contracts would add
compatibility code without protecting a released client.

## Decision

Server accepts a paper ingestion atomically. For an uploaded PDF, object storage
is content-addressed first; then the reservation, canonical Document reference,
personal Library membership, DurableJob, and dispatch outbox record commit in
one database transaction. A successful `202` returns the canonical ingestion
projection that the Library list can immediately render.

One operation-scoped idempotency key owns an uncertain submission. A client
that loses the response reconciles or repeats the same request with the same key
and parameters. Replaying a completed operation returns its terminal projection;
replaying a cancelled operation never resurrects it.

The worker reports bounded stage progress and a heartbeat for `queued`,
`parsing`, `extracting`, `indexing`, and `finalizing`. Soft and hard task limits
bound the workflow. Cancellation is a Server-owned terminal transition exposed
by `DELETE /api/v1/paper-ingestions/{job_id}`. Pending work is revoked without
terminating the worker process; running work observes cooperative cancellation
at stage boundaries. Signed callbacks are idempotent no-ops after cancellation.

The Papers endpoint returns one discriminated union of completed papers and
active/failed ingestions. Web renders that union as one canonical table/list,
uses local state only for pre-acceptance upload progress, and never displays a
detached processing banner. Each personal membership occupies exactly one
position in that union: its active or failed ingestion projection replaces the
normal paper projection until processing completes.

Web hashes selected PDF bytes to collapse duplicate selections before they
enter the local queue. This is interaction feedback, not an integrity boundary;
Server content-addressing, quota-owner locking, and membership uniqueness remain
authoritative for concurrent clients and already-imported documents.

## Alternatives considered

- Return an upload token and create the Library row later. Rejected because the
  browser cannot distinguish accepted work from a lost response.
- Revoke running Celery work with process termination. Rejected because task
  termination is unsafe and cannot guarantee provider or storage cleanup.
- Keep a separate ingestion-status collection in Web. Rejected because it
  creates two row authorities and the visual jump reported during acceptance.
- Keep compatibility fields and translate them. Rejected because Scholens is
  unreleased and the translation would become avoidable permanent debt.

## Consequences

The acknowledgement path does slightly more database work, but it establishes a
strong product boundary: after `202`, the accepted item exists and is listable.
Object cleanup remains asynchronous and idempotent. Jobs must report progress
and check cancellation at every expensive boundary. Web must retain an
operation key until an uncertain request is reconciled, then retire it only at a
known terminal outcome.

## Validation

Server tests cover atomic acceptance, idempotent replay, cancellation, late
callbacks, source validation, and list projection. Jobs tests cover heartbeats,
stage progress, cooperative cancellation, and bounded deadlines. Web tests and
Storybook cover queued removal, in-flight cancellation, partial upload failure,
same-key recovery, standard ingestion rows, retry, and mobile containment.
Manual acceptance uses a local PDF and arXiv `1706.03762` against the persistent
local stack.
