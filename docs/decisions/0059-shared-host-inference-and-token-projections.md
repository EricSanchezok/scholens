# 0059 — Shared host inference and token projections

Status: Accepted
Date: 2026-09-27
Owners: Scholens Server and Jobs maintainers

## Problem

Per-process local model loading makes cold starts expensive and allows document
workers to compete with the API for large inference allocations on one host.
Five-line overlapping passages have variable token counts and duplicate work.
Running query inference inside a database transaction holds a connection while
waiting for CPU and can extend unrelated API latency.

## Decision

The model artifact registry gives O4, FP32 evaluation and ARM64 INT8 distinct
persistence revisions and pinned model/tokenizer digests. Runtime selection is
explicit and artifact validation fails before inference on a mismatch. The
INT8 artifact is reproducibly converted in the locked Debian model build stage;
only files reach the Alpine application image. Provider imports are lazy at the
package boundary so the inference process owns no provider SDK graph. The O4
default preserves the existing deployment until the measured, versioned
projection rollout selects INT8.

Use one private Unix-socket inference process per host, with an exclusive owner
lock, bounded wire data, a single model thread, query priority, and bounded index
microbatches of one text. On the existing ARM host with a 0.75-CPU cap, concurrent
long-input indexing and 120 queries produced 64 query deadline fallbacks with
two-text batches, versus four with single-text batches. All index requests
completed in both runs. This bounds the non-preemptible work instead of extending
the interactive deadline. A client deadline yields lexical search; it must never create a
fallback model in the API process. Prepare query vectors before database work,
and require query digest/model revision agreement before semantic SQL ranking.

Periodic readiness checks use a standard-library command path and shared socket
framing/deadlines. The narrow health response requires an exact revision, no
vectors and no error; the server retains its full request validation. Model,
provider, validation and telemetry runtimes load only for their owning operation.
This avoids repeated imports competing with user requests on the shared CPU.

Add token windows as a separately versioned projection primitive. Bound tokenizer
lookahead, preserve exact source character and line coordinates, and prefer
paragraph boundaries. Existing five-line projections remain available through
consumer rollout; activation requires versioned persistence and complete-index
adoption. A partial or failed rebuild cannot erase the previous usable index.
Separate tables use document/model revision heads and ordinal passage keys, so
multiple token windows can share one canonical line. Source digests maintained
by a database trigger also invalidate projections written before an N-1 source
update. Validate all coordinates and vectors before replacing a head; bounded
insert batches share the final atomic transaction. Legacy rows remain available
for N-1 rollback but are suppressed once the selected revision is adopted.
The additive migration avoids a blocking full-table text rewrite.

## Alternatives considered

Larger instances violate the deployment constraint. Per-worker model caching
retains multiple model lifetimes and repeats cold starts after worker exit.
Unbounded shared batches improve throughput at the expense of interactive tail
latency. Replacing existing passage coordinates in place breaks citations and
removes a safe rollback path.

## Consequences

The host gains one internal process and private mount, without a public service
or new host tier. Socket permissions, measured hard limits, lifecycle health,
queue pressure and query fallback become deployment acceptance requirements.
Model precision is selected using native-host latency, memory and bilingual
retrieval evidence. File size and another CPU's benchmark are insufficient.

## Validation

Real socket tests cover priority between microbatches, serial model execution,
revision rejection, deadline/disconnection, saturated capacity and oversized
headers. Search workflow tests prove inference precedes database work. Token
fixtures prove exact multilingual coordinates, stable identities and bounded
lookahead. The reproducible offline benchmark reports model/corpus hashes and
synthetic-fixture limitations; production activation has separate rollout gates.
