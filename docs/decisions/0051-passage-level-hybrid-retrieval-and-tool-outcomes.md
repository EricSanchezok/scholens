# 0051 — Passage-level hybrid retrieval and explicit tool outcomes

Status: Accepted
Date: 2026-09-05
Owners: Scholens platform team

## Problem

The document-level semantic projection introduced by ADR 0030 is useful for
finding papers by title or broad topic, but it cannot reliably recover a
specific claim expressed only in the body. At the same time, Conversation and
MCP tools exposed transport-specific errors and reduced every successful call
to the same visual state. A valid empty search could therefore look like a
failure, while a mutation that made no change looked identical to one that did.
Those ambiguities encouraged unnecessary retries and unsupported claims about
what had or had not been searched.

The solution must preserve authorization-first retrieval, keep paper text and
queries local, remain available with an incomplete vector backfill, preserve
the existing public tool names, and allow adjacent Server, Jobs, and Web
versions to coexist during deployment.

## Decision

Extend the canonical `DocumentPassage` search projection with nullable,
model-revision- and content-digest-bound vectors. Jobs computes passage vectors
from canonical parser Markdown in bounded batches and transfers them to Server
as a deterministic, checksummed binary S3 artifact. Server validates the exact
job-owned key, size, digest, model revision, dimensions, normalization, and
record count (at most 10,000 passages and 16 MiB) before atomically replacing
the passage projection. The callback
body contains only artifact metadata. Existing passages are indexed through a
bounded dry-run-first maintenance command that performs model inference outside
a database transaction and revalidates each content digest before writing.

The PostgreSQL adapter embeds a query once and combines authorized document and
passage cosine candidates with the existing exact, trigram, and full-text
lanes. Semantic passage excerpts retain exact line locators. Lexical retrieval
is always available: a missing model, incomplete vector coverage, rejected
artifact, or semantic-query failure degrades to the previous lanes rather than
failing the request. Responses expose the active search mode, retrieval modes,
and both document- and passage-index coverage.

The shared tool catalog now also owns a stable domain and intent for every
definition. Both Conversation and MCP project errors through one structured,
actionable error boundary. Successful internal outcomes carry one of
`results`, `empty`, `changed`, or `unchanged`, plus an optional result count;
Conversation activity exposes those additive fields so the Web can distinguish
an expected empty result from a technical failure. Tool names, input contracts,
and permission boundaries are unchanged.

## Alternatives considered

- Embed whole parser documents only. Rejected because long papers dilute local
  claims and exceed the useful input size of the pinned embedding model.
- Put vectors directly in the signed callback JSON. Rejected because base64 or
  float JSON would greatly amplify callback size and memory use.
- Add a vector database or hosted embedding provider. Rejected because
  PostgreSQL already owns authorization and derived search state, and local
  inference avoids a new availability and disclosure boundary.
- Let the model infer success or failure from arbitrary tool payloads. Rejected
  because transports and UI need deterministic low-cardinality semantics.
- Replace or rename overlapping search tools. Rejected because exact
  within-paper search and conceptual cross-library retrieval are distinct
  intents and existing MCP clients require compatibility.

## Consequences

Passage vectors increase PostgreSQL storage and require an additive HNSW index,
but remain rebuildable derived data. Jobs and Server share a small safe artifact
codec; malformed artifacts are never deserialized as executable objects. A
model revision requires both document and passage reindexing. Coverage can be
temporarily partial without changing availability, and operators can observe
that state without recording raw user queries.

Tool success is more honest and recoverable, but every new tool must provide a
unique intent and domain and must return data from which the shared outcome
classifier can derive an accurate presentation. Error codes and outcome classes
are low-cardinality telemetry fields; messages, arguments, queries, and paper
content remain excluded.

## Validation

CI validates the artifact codec, callback tamper rejection, digest revalidation,
authorization predicates in every semantic lane, lexical degradation, catalog
intent uniqueness, actionable error projection, additive generated contracts,
Conversation source materialization, and localized Worklog outcome states. The
32-case redacted reliability manifest covers routing, retrieval, recovery, and
citation behavior; staging runs it three times before rollout. Production
monitors tool outcome/failure classes, search result counts, and both semantic
coverage ratios. Revisit the ranking thresholds only with labeled relevance
evidence.
