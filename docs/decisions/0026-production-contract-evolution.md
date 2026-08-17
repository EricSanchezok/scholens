# 0026 — Production contract and schema evolution

Status: Accepted
Date: 2026-08-17
Owners: Scholens

## Problem

Scholens is deployed with durable production data, a browser-facing v1 API,
external MCP clients, immutable release manifests, and protected migrations.
The previous reset-first rule assumed disposable product rows and allowed an
intentional breaking change to replace schema, routes, DTOs, and tests in one
change. Continuing that rule after deployment could lose user data or break a
client that is not upgraded atomically with Server.

The release contract also required the live migration head to equal a target
release's head. That prevented rollback to an older application after even a
compatible additive migration.

## Decision

Production data and applied migrations are durable from revision
`c9f4a62d01ab`. Later schema changes use expand–migrate–switch–contract and a
monotonic minimum compatible application revision. Release manifests record
the complete ordered migration chain and per-revision checksums. Deployment may
select any application revision inside the live compatibility range.

HTTP `/api/v1` and MCP `/mcp` are stable public contracts. Incompatible
replacements use a new major boundary or tool while the old transport adapter
continues to call the canonical application use case. Deprecated public
contracts remain for at least 90 days and until telemetry shows 30 consecutive
days without use.

Compatibility code is permitted only at HTTP, MCP, job-envelope, or persistence
boundaries. Domain and application code retain one current model. Every
temporary adapter has an owner, replacement, telemetry identity, and objective
removal condition.

This decision supersedes every reset-first or disposable-product-data clause
in earlier ADRs. It amends the exact-migration-head rollback rule in ADR 0022;
the rest of those decisions remains accepted.

## Alternatives considered

- Keep reset-first until a later general-availability milestone. Rejected
  because deployment and durable user data, not a marketing label, create the
  migration obligation.
- Preserve every historical shape inside business code. Rejected because it
  creates multiple authorities and makes compatibility debt permanent.
- Require exact database head for every rollback. Rejected because safe
  additive migrations should not eliminate the last known-good application.
- Run reverse migrations during rollback. Rejected because destructive reverse
  DDL is less predictable than a forward-compatible schema and can discard
  data written by the new release.

## Consequences

Breaking changes take multiple releases and require explicit deprecation or
migration evidence. Release metadata and CI become more complex, but
compatibility is bounded, visible, and removable. Application rollback remains
available across additive migrations and stops deliberately when a contract
migration advances the compatibility floor.

The first release using manifest contract v3 must make no schema change. It
converts the existing live proof at `c9f4a62d01ab` into the new compatibility
model and becomes the rollback anchor for later migrations.

## Validation

CI rejects changed historical migrations, incomplete migration policy,
breaking HTTP/MCP v1 diffs, destructive expand revisions, lost seeded rows,
and non-monotonic compatibility floors. Release tests prove legacy-proof
transition, additive rollback, contract-floor rejection, and fail-closed
recovery behavior.
