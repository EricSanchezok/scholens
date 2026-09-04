# 0048 — Worker-first paper ingestion with staged materialization

Status: Accepted
Date: 2026-09-04
Owners: Scholens platform team

## Problem

The API accepted arXiv, DOI, URL, and staged-upload papers by downloading the
complete PDF into Python memory before creating a durable job. Batch acceptance
could perform four such downloads concurrently, exhausting the 2 GiB API task
and producing worker SIGKILLs and ALB 502 responses. The existing document worker
already has bounded concurrency, late acknowledgements, and SQS redelivery.

## Decision

Paper source acceptance creates a durable PDF job and an `UploadReservation`
whose digest and byte reservation are initially nullable/zero. The job payload
contains a controlled source descriptor and a deterministic staging key. The
document worker revalidates URL security and response limits, streams bytes to a
temporary file, computes SHA-256 incrementally, uploads the staging object, and
sends a signed metadata-only `source_ready` callback. Server verifies the
staging HEAD while holding the existing account quota locks, copies the object
server-side to `documents/{sha256}/source.pdf`, materializes or reuses the
Document and memberships, and returns whether processing is required. The
worker parses the same local file and uses the existing bounded terminal PDF
callback. Repeated callbacks use the same job/staging key and are idempotent;
single-flight is provided by canonical fingerprints and durable idempotency
keys. No new ECS service, queue, Redis instance, or always-on task is added.

## Alternatives considered

- Increasing API task memory or Cloudflare/ALB timeouts: rejected because it
  preserves the memory-amplifying data path and raises recurring capacity cost.
- Adding a dedicated source-download service or queue: rejected because the
  existing document worker already owns PDF processing and can scale on its SQS
  backlog.
- Keeping PDF bytes in callbacks: rejected because callback bodies are bounded
  and would recreate the API memory pressure.

## Consequences

API acceptance is fast and memory-stable, while source failures become durable
worker failures with host/status/attempt diagnostics. Staging objects require
the existing lifecycle cleanup and are retained until parsing completes. The
reservation digest is nullable during materialization, so all digest queries and
project-transfer repricing must explicitly handle that state. Source retries
are safe only while the deterministic staging object remains available.

## Validation

Run Server and Jobs ingestion tests, exercise a 50-item batch and concurrent
25–30 MiB sources, and verify API memory stays below 75% with zero SIGKILL/ALB
502 events over 24 hours. Revisit the design only if queue drain or staging
retention cannot meet the existing document-worker scaling envelope.
