# 0034 — Read-only shared profile avatars

Status: Accepted
Date: 2026-08-21
Owners: Scholens

## Problem

SanchezCloud Account Center owns one private profile avatar per identity, but
Scholens rendered generated initials in the workspace shell, Settings, Project
membership, and Reader discussions. Copying image bytes or avatar references
into `scholens.*` would create a second profile source of truth. Returning a
permanent or public object URL would weaken the private-bucket boundary, while
letting browsers query Identity storage directly would expose credentials and
authorization details outside the Server.

## Decision

Scholens reads shared avatars through the pinned SanchezCloud Identity SDK. The
API runtime receives `SELECT` on `auth.user_avatars`, `s3:GetObject` on only
`auth/avatars/v1/*`, and KMS decrypt constrained to S3 plus that exact encryption
context. It receives no avatar insert, update, delete, upload, encrypt, or
data-key permission. Workers, schedulers, migrations, MCP, and the browser
receive none of these capabilities.

The Server exposes `GET /api/v1/me/avatar` for the authenticated caller.
Existing authorized Project-member and annotation-list responses are additively
enriched with short-lived avatar views only after their normal product
authorization has succeeded. Actor and the canonical Project and Research
operation DTOs remain avatar-free; dedicated additive HTTP response contracts
contain the view, so presigned URLs do not enter domain logic, durable state,
logs, jobs, or MCP output. Batch presentation deduplicates visible user IDs and
bounds concurrent SDK calls. The infrastructure adapter keeps a bounded LRU of
positive views until one minute before URL expiry, a one-minute negative cache,
and a per-user single-flight so polling does not repeatedly query Identity or
re-sign the same S3 object. Dependency failures are never cached. A missing
avatar or batch-read failure falls back to initials without failing the Project
or Reader operation.

Web keeps one reusable avatar primitive. Current-user and embedded collection
queries refresh one minute before the earliest URL expiry, never less than
thirty seconds apart; missing avatars are polled every fifteen minutes. A broken
current image invalidates its query at most once per version in ten seconds.
Images are decorative wherever the adjacent name already supplies accessible
identity.

Scholens does not add avatar upload, edit, or delete controls. Account Center
remains the only management surface and data owner.

## Alternatives considered

- Copy avatar bytes or object keys into `scholens.*`. Rejected because it
  creates divergent profile state and an unsolved synchronization/deletion
  lifecycle.
- Put the avatar URL on the shared Actor. Rejected because Actor crosses
  application and MCP boundaries where expiring transport credentials do not
  belong.
- Add an authenticated arbitrary-user avatar endpoint. Rejected because it
  enables identity enumeration unless every caller repeats product visibility
  authorization.
- Fetch one public Gravatar-style URL from email. Rejected because it leaks an
  identifier to a third party and ignores the Account Center source of truth.
- Proxy image bytes through Scholens. Rejected because it adds bandwidth,
  caching, and range/streaming responsibility without improving authorization.

## Consequences

The API runtime has one explicit read-only cross-schema and cross-bucket
capability that must be audited in addition to Identity's base
`product-runtime` profile. Production startup fails if the shared bucket name is
absent. Local development remains initials-only unless a non-production shared
avatar bucket is explicitly configured.

The public HTTP contract grows additively, and generated Web types must change
with it. Presigned URLs may expire while a page is open, so clients must retain
the scheduled refresh and fallback behavior. SDK batch support would reduce
database round trips in the future; until then Scholens bounds and deduplicates
the SDK's public single-user reads rather than duplicating Identity SQL.

## Validation

Server tests cover present, missing, unavailable, deduplicated Project, and
annotation creator cases, plus positive expiry, negative expiry, failure retry,
and per-user single-flight behavior. Deployment tests assert exact read-only
database, S3, KMS, runtime, and workload boundaries. Web unit and Storybook
coverage verify refresh timing, real-image rendering, compact sizes, and initial
fallback.
