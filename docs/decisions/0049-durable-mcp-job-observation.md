# 0049 — Durable MCP job observation over SSE

Status: Accepted
Date: 2026-09-05
Owners: Scholens platform team

## Problem

Paper ingestion was durable, but the MCP response remained a single buffered
JSON body. An Agent could select a 60-second observation window while its host
also enforced a 60-second tool deadline, so acceptance and serialization
overhead produced MCP `-32001` even though the job continued normally. Longer
windows also crossed reverse-proxy idle limits. DOI resolution still performed
provider I/O before job creation, and retry loaded the canonical PDF into API
memory, leaving two paths where a lost response could lack a durable handle or
reintroduce the original memory risk.

## Decision

`wait_seconds` remains an Agent-selected input from 0 through 240 seconds, with
a 30-second default. It is bounded observation, not a success deadline: once a
job is committed, an elapsed observation returns the latest authorized active
snapshot and job UUID as a successful tool result. MCP reserves three seconds
from the selected window for projection and delivery, and batch acceptance is
bounded to five seconds before all accepted jobs share the same request
deadline.

The Streamable HTTP endpoint uses its SSE POST response form. Headers are sent
immediately and the protocol runtime emits a keepalive every 15 seconds.
Official client guidance sets a 270-second absolute call timeout for the public
240-second maximum. The local connector charges hashing, preparation, and
upload against one observation budget before forwarding the remainder.

DOI jobs are committed after local identifier and connection validation but
before OpenAlex network I/O. A signed job-scoped callback resolves only that
persisted DOI and returns only its open-PDF URL; credentials remain in Server.
Retry creates a new immutable job whose document worker streams the canonical
S3 source and uses the same staged materialization path. No PDF bytes pass
through MCP callbacks or the API process.

## Alternatives considered

- Fixing `wait_seconds` at 30 seconds: rejected because callers legitimately
  choose different latency/turn tradeoffs and the public 0–240 contract is
  useful.
- Returning an MCP transport error when observation expires: rejected because
  transport failure misrepresents a valid durable operation and discards its
  continuation handle.
- Depending on experimental MCP Tasks: rejected for this release because
  Scholens already owns a stable DurableJob contract and the primary clients do
  not yet consume the evolving Tasks extension consistently.
- Raising Cloudflare, ALB, API memory, or service counts: rejected because SSE
  keepalives and worker-owned files solve the failure without recurring
  capacity cost.

## Consequences

Conformant clients must accept SSE responses to Streamable HTTP POST requests
and configure an outer timeout consistent with the wait they request. Client
cancellation stops only observation; it never cancels accepted work. Provider
and parsing failures after acceptance are visible on the durable job, while
invalid input or missing required integration can still fail before a job
exists. DOI resolution adds one small signed callback and retry adds no API
memory proportional to PDF size.

## Validation

Server tests cover shared deadlines, expired-window snapshots, SSE response
shape, and job-scoped DOI resolution. Jobs tests cover signed source resolution
classification and worker streaming. Connector tests cover the single local
observation budget. Production acceptance uses 60-, 130-, and 240-second waits
through Cloudflare and verifies an active or terminal job result without
`-32001`, 502, or 524 responses.
