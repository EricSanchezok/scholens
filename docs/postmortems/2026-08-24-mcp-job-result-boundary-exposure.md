# MCP Job results crossed the public Agent boundary

- Date: 2026-08-24
- Status: Final
- Severity: SEV-2
- Owners: Scholens

## Summary

The first complete live MCP audit found that authenticated Job tools reused the
durable internal `JobResponse` without a public runtime projection. Completed
Job results could therefore return extracted paper text, provider payloads, and
object-storage implementation keys to an Agent, and large result objects were
duplicated in MCP compatibility text and structured content. Scholens approved
an emergency boundary correction on 2026-08-24.

The correction keeps the published Job schemas parseable for existing clients
but always emits `result: null` over MCP. Status-list queries no longer select
the durable payload or result JSON columns. Exact, batch, ingestion, and legacy
replay paths use the same status-only projector and complete-envelope budgets.

## Impact

An authenticated user or Agent with access to its own Job could receive more
internal processing data than the MCP product contract intended. The audit
measured multi-megabyte list responses and identified internal object-key and
raw-content fields. No credential value, cross-tenant authorization bypass,
malicious access, or confirmed third-party exfiltration was identified. The
exposure was limited by the existing Job ownership checks, but those checks did
not make worker-only fields appropriate for an Agent response.

## Detection

The issue was found by exercising the configured MCP tools against real data and
measuring the serialized responses. Unit tests previously validated business
models rather than the complete MCP `CallToolResult`, so they did not detect the
duplicated compatibility body or Resource Link overhead.

## Timeline

- 2026-08-24 — Full MCP audit measures oversized Job responses and identifies
  worker-only fields in the public result.
- 2026-08-24 — Code review traces the exposure to direct reuse of durable Job
  responses and incomplete envelope measurement.
- 2026-08-24 — Scholens approves the security correction while requiring the
  existing public schema to remain parseable.
- 2026-08-24 — Status-only SQL reads, null-result projectors, legacy replay
  sanitation, complete-envelope enforcement, and regression tests are added.

## Contributing factors

- One DTO served both durable worker recovery and an Agent-facing transport.
- The original size check did not measure compatibility text,
  `structuredContent`, and standalone Resource Links together.
- Job list and batch shapes repeated resource information already present as
  stable document and Project identifiers in every item.
- Contract evolution was considered after the initial projection design rather
  than before changing a published schema.

## Resolution and recovery

MCP Job projections preserve the historical `object | null` schema but set the
runtime value to null before output validation, replay persistence, and
serialization. `list_jobs` uses a status-only repository query and signed
keyset pagination. Exact and ingestion projections keep bounded resource links;
multi-Job and batch responses keep all resource IDs in their typed payloads but
do not duplicate every ID as standalone links. Full Unicode worst-case tests
measure the real `CallToolResult` and remain within the per-tool budgets.

The HTTP Jobs API and durable worker records are unchanged. Deployment and
post-release telemetry remain release responsibilities; no data rewrite is
required.

## Corrective actions

| Action | Owner | Status | Tracking link |
| --- | --- | --- | --- |
| Add status-only Job repository reads | Scholens | Complete | Current PR |
| Project every MCP Job result to `result: null` | Scholens | Complete | ADR 0042 |
| Sanitize legacy invocation replays before delivery | Scholens | Complete | Current PR |
| Measure the complete MCP success envelope | Scholens | Complete | ADR 0040 |
| Add worst-case Unicode and batch budget tests | Scholens | Complete | Current PR |
| Monitor deprecated MCP reads and Job budget failures after release | Scholens | Open | Release follow-up |

## Lessons

Authorization and projection answer different questions: a user may own a Job
without every durable Job field being public. Compatibility should preserve a
client's parseable schema, not an unintended disclosure. Byte budgets must be
measured on the exact transport object, including representations duplicated
for MCP client compatibility.
