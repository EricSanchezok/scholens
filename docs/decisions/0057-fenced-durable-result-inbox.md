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
