# 0040 — Bounded MCP public projections and lossless continuation

Status: Accepted
Date: 2026-08-24
Owners: Scholens

## Problem

The first complete live audit of the Scholens MCP boundary showed that a valid
request could consume megabytes of Agent context. Durable job records exposed
worker-only results and object-storage keys, paper reads bounded line count but
not bytes, and a failed resource serialization could amplify a nested validation
error to roughly ten megabytes. The research-output catalog also described a
smaller set of values than its list projection returned.

These were boundary failures rather than isolated serializer bugs. Internal
records are optimized for recovery and service coordination; MCP responses are
optimized for safe reasoning by an untrusted, context-limited client. Reusing
one representation for both responsibilities makes accidental disclosure and
unbounded growth likely to recur.

## Decision

Treat every MCP tool result and resource as an explicit public projection. A
projection includes only stable identifiers, user-facing state, actionable
errors, bounded source excerpts, and resource links. Worker payloads, storage
keys, raw provider results, callback bookkeeping, and other service-internal
fields never cross this boundary merely because they exist on a durable model.

Give each tool definition and every resource family an explicit UTF-8 envelope
budget in the generated public MCP contract. Enforce the tool budget against
the real MCP `CallToolResult`, including its compatibility text block,
`structuredContent`, and standalone Resource Links. Normal successful growth
uses bounded keyset pagination or a signed continuation token; a response is
never made to fit by silently removing arbitrary JSON fields. Paper content
continuation is exact and offset-based so concatenating every page reproduces
the canonical text byte-for-byte, including long lines and multi-byte Unicode.
Paper metadata and individual Research outputs use the same lossless pattern
over canonical JSON: concatenate UTF-8 fragments, verify their shared SHA-256,
then parse the complete document. Transient signed audio access remains outside
that canonical document so URL rotation cannot invalidate continuation.

Resource serialization recursively normalizes supported Python and Pydantic
values into JSON before validation. Oversized aggregate resources return a
small typed envelope with every continuation needed for their independent
paper, member, output, metadata, and content sections. Single-object Resources
continue through the corresponding lossless JSON tool. Unexpected resource
failures use stable bounded JSON-RPC errors rather than raw validation
diagnostics.

Strict JSON normalization is shared by fresh success, invocation replay, error
details, Resources, and transport serialization. Non-finite numbers, reference
cycles, ambiguous mapping keys, and unsupported values fail closed. Signed
cursors require one canonical unpadded URL-safe Base64 spelling in addition to
valid HMAC and request binding, so alternate padding-bit encodings cannot create
cache or idempotency aliases.

Keep one public semantic set for each concept. Research-output list, get,
resource, and schema surfaces all support the same four stored kinds; generation
tools remain a separate three-kind capability. Public Job status projections
retain a compatibility `result: null` field but never expose the durable result.

Confirmation-enabled tools validate every non-mutating business precondition
before issuing a state-bound token. An impossible request returns its stable
business error, and an already-satisfied request returns an idempotent receipt.

## Alternatives considered

- Raise only the client or proxy response limit. Rejected because it preserves
  disclosure and context-exhaustion risk while moving the eventual failure.
- Apply one global character truncation middleware. Rejected because JSON and
  Unicode can be corrupted, important fields can disappear without a contract,
  and callers receive no lossless continuation path.
- Expose durable Job results but redact a short deny-list of known keys.
  Rejected because new internal fields would be public by default and nested
  provider payloads cannot be made safe with a fragile blacklist.
- Keep annotations outside the research-output read contract while returning
  them from the default list. Rejected because list-to-get closure is a basic
  requirement for an Agent-facing collection.

## Consequences

MCP adapters and projectors intentionally differ from internal HTTP and worker
contracts. New tools must choose a budget and continuation strategy, and new
durable fields remain private until deliberately projected. Research-output
lists use a dedicated SQL summary catalog: they select bounded scalar previews
without hydrating transcripts, table rows, comments, or signed object URLs.
Exact page tokens add signing and stale-content checks, but callers can reason
incrementally without losing text. Cached paper regex search has a separate
process-level concurrency gate and scans source spans directly, so a cache hit
cannot multiply CPU scans or allocate full-line copies outside the cache-build
budget.

The generated MCP snapshot becomes larger because it records tool, resource,
template, and budget metadata. Compatibility checks reject accidental tool or
resource removal, schema narrowing, safety-policy drift, and reduced published
budgets. HTTP Job responses remain unchanged.

## Validation

- Contract tests enumerate all public tools, resources, templates, confirmation
  policies, and envelope budgets.
- Projection tests seed oversized nested results and prove internal keys and raw
  content cannot escape through list, get, wait, batch, or replay paths.
- Unicode paging tests reassemble Chinese, emoji, control characters, and a
  single line larger than one page exactly; tampered and stale cursors fail.
- Regex tests search an eight-megabyte single line through a slice guard, prove
  only the fixed match preview is copied, and exercise cache-hit search
  concurrency admission.
- Resource tests cover nested Pydantic values, UUIDs, datetimes, oversized
  payloads, and bounded JSON-RPC failures.
- Confirmation tests prove invalid and idempotent states never mint a token.
- `./scripts/run-gates.sh server`, `mcp-connector`, and `docs` own the affected
  deterministic checks.
