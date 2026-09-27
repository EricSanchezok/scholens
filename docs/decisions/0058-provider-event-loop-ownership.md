# 0058 — Provider event-loop ownership

Status: Accepted
Date: 2026-09-27
Owners: Scholens Server maintainers

## Problem

Citation recovery used a synchronous facade that created an event loop for each
OpenAlex request. The application-owned async HTTP and Redis clients could then
reuse pooled resources belonging to a closed loop. Connector calls had another
per-request async-to-sync bridge. Catching these errors made enrichment appear
successful while silently dropping available bibliographic fields.

## Decision

Keep citation preparation, metadata recovery, connector I/O and OpenAlex calls
async all the way from HTTP, MCP and Job workflow entrypoints. The application
owns async clients and closes them in its lifespan on the same event loop.
Remove the unused per-call loop bridges instead of retaining competing client
lifetimes. Offload synchronous database commands, Crossref requests and the
synchronous LLM backend with context propagation. No provider request retains a
database session. Credential outcome writes retain the revision actually used.

Product DeepSeek calls create a provider-owned HTTP transport and enter the
Agent context for the whole operation, including streaming. They close it on
success, error, cancellation, and explicit stream closure on the same loop.
The conversation wrapper explicitly closes its inner event generator. Passing
an externally created OpenAI SDK client to the provider relinquishes transport
ownership and is therefore not used by product DeepSeek profiles. Configured
endpoint, timeout, and retry limits remain unchanged. This per-operation
ownership is distinct from application-lifetime OpenAlex pooling.

## Alternatives considered

A new client per request discards connection pooling and spreads cleanup policy.
A dedicated background event loop plus blocking bridge avoids closed loops but
retains two lifetimes and deadlock risk. Retrying the closed-loop error does not
repair ownership and can repeat external work.

## Consequences

Internal citation workflow methods become async; public HTTP and MCP shapes
remain unchanged. Persistence application remains synchronous and transactional.
The synchronous LLM backend still needs its own bounded provider timeout; task
cancellation alone does not terminate its underlying request.

## Validation

Tests assert repeated provider calls run on the caller's loop, credential reads
and outcome writes run off that loop, credential revisions remain independent,
and canonical citation patches still apply in one command. Existing connector,
PDF postprocess, citation authorization and complete Server suites remain gates.
No-network transport tests verify DeepSeek client closure on success and
cancellation; the conversation cancellation test verifies model context exit.
