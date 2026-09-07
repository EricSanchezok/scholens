# ADR 0052: User-owned AI and capacity-only plans

Status: Accepted for the next release; no production rollout in this change.

## Problem

A small personal deployment needs bounded infrastructure capacity without
subsidizing model calls or introducing public payments. Existing plans advertise
large token allowances and a redundant per-Project paper quota.

## Decision

Scholens requires each user to connect a DeepSeek API key for model-backed
operations. Basic and Researcher both use the caller's credential. The product
provides no shared model key, token allowance, or token billing. Fixed model
profiles remain deployment-owned; user credentials only reach DeepSeek's
explicit official endpoint. Non-model reading and organization stay available.

Basic includes 200 unique papers, 1 GiB and 10 Projects. Researcher includes
2,000 unique papers, 10 GiB and 50 Projects. There is no separate per-Project
paper cap. Owner-level unique-document and storage reservation checks still
apply to uploads, collaboration and ownership transfers. Existing over-limit
content is retained; new additions must fit the effective account capacity.
Public payments remain disabled and audited internal Researcher grants remain.

## Consequences

Connections owns encrypted credentials in `scholens.integration_connections`.
The additive migration widens the provider check without altering existing
rows or any Identity-owned schema. Server resolves keys in the authenticated
workload context; Jobs fetches them over a signed job-scoped route after claim,
using the durable job requester's identity. Queue envelopes contain no keys.
Missing/disabled connections produce actionable errors. PDF ingestion skips
optional AI metadata when the owner has no connection and retains deterministic
PDF processing. There is no fallback to a deployment key.

`GET /api/v1/billing/capacity` is the current capacity-only contract. The old
`GET /api/v1/billing/usage` remains deprecated at its HTTP adapter with retired
zero token fields and an unbounded per-Project sentinel for old clients. Its
removal is governed by `server/contracts/deprecations.json`, owned by
Scholens platform. Historical usage tables and accepted callback fields remain
readable but new processing writes no token counters. The legacy settlement
adapter can be removed once old producers and queued callbacks have drained.

Scholight's endpoint and delegation remain unchanged. Shared Identity,
production credentials and databases are not migrated by this change. Apply
the additive migration before the next application deployment. A previous
application can still read all pre-existing rows; rollback leaves new DeepSeek
rows unused. Do not roll workers forward before Server supports the credential
route. No Release workflow is authorized here.

## Alternatives considered

Reducing free token allowances would be a smaller immediate edit but retains
two payment sources and subsidy accounting. For a small personal deployment,
requiring BYOK gives a clearer operating boundary. Destructively deleting old
usage tables or rewriting applied migrations is unnecessary and would damage
rollback and historical data. Charging users is deferred until payment setup
and the migration budget are ready.
