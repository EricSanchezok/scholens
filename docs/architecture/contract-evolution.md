# Production contract and schema evolution

Scholens is a deployed product. Iterative delivery remains the development
model, but production data and published contracts are durable. This document
is the current owner for compatibility, migration, deprecation, and removal
rules. [ADR 0026](../decisions/0026-production-contract-evolution.md) records
why the repository moved away from its pre-release reset-first policy.

## Stable boundaries

| Boundary | Compatibility promise |
| --- | --- |
| PostgreSQL `scholens.*` | Applied revisions and production data are durable. Schema changes are forward-only and preserve every supported application revision. |
| HTTP `/api/v1` | Existing valid requests and documented responses remain compatible. Breaking changes use another major API boundary. |
| MCP `/mcp` | Existing tool names, schemas, permissions, and safety semantics remain compatible. Breaking changes use a replacement tool or versioned endpoint. |
| Internal HTTP and job payloads | Producer and consumer overlap safely during rolling deployment and while accepted jobs remain queued. |

Conversation citation summaries and optional fields on the `references` SSE
event are compatible output extensions. Older clients may ignore them; the
server continues to emit the existing `references` object and lifecycle event
types. Citation metadata may be empty when evidence was retrieved but could not
be safely attached, while the response itself remains completed. A future
`citation_update` event must be additive and idempotent and may update only
references/trace, never the persisted answer text.

The production database baseline is revision `c9f4a62d01ab`. The protected
database workflow must verify that value against `migrations/current.json`
when establishing the version 3 release contract; repository text never
overrides live evidence. The independently owned `auth.*` schema keeps its own
migration and compatibility policy.

## Change classes

Every pull request that touches a stable boundary selects one class:

- **Internal:** no stored data or published wire contract changes.
- **Compatible:** adds optional input, additive output, a new route/tool, or an
  additive database structure that old applications ignore safely.
- **Deprecated:** retains the old contract at its boundary, identifies its
  replacement, and starts the removal clock.
- **Contract:** removes an already-retired database or public boundary after
  its recorded exit conditions have been satisfied.

A contract change is never disguised as a refactor. A security or active data
integrity incident is the only emergency exception; it requires an incident
record, explicit owner approval, consumer communication, and follow-up tests.

### Correcting an inaccurate published schema

A generated schema may occasionally be less restrictive than the request
validator that was already deployed—for example, when a Pydantic model
validator enforced a relationship that JSON Schema did not express. Aligning
the schema with that existing runtime boundary is a correction, not permission
to narrow accepted requests. Each HTTP or MCP correction must be registered in
`server/contracts/schema-corrections.json` with its exact operation or tool,
JSON pointer, old-value state, new-value SHA-256, owner, rationale, and a
deterministic runtime-evidence test.

The evidence reference must resolve to an exact top-level pytest node under
`server/tests/`; substring-only or comment-only references are rejected. The
dependency-free compatibility lane validates that structure, while the Server
lane collects and executes the referenced test as part of its complete suite.

The compatibility job supplements the pinned `oasdiff` release by detecting
restrictive request keywords it does not reliably report, then accepts only an
exact registry match. Correction entries are immutable tombstones, and a new
entry is valid only in the transition that introduces its matching generated
schema change. If the previous runtime accepted the request, the change is not
a correction: retain the legacy behavior or publish a replacement boundary.
After exact target, pointer, old-value, new-value digest, and evidence checks
pass, CI applies only the active registered values to temporary HTTP/MCP
comparison bases before invoking `oasdiff`; committed historical snapshots are
never rewritten and unregistered restrictions still fail closed.

## Database lifecycle

Applied migration files are immutable: do not edit, rename, delete, reorder, or
squash them. Add one or more new revisions and classify each in
`server/migrations/policy.json`. The graph remains one linear chain.

Schema replacement follows separate releases:

1. **Expand:** add nullable columns, tables, indexes, or otherwise compatible
   structures. Do not drop or rename objects, narrow types or enums, make an
   existing column non-nullable, add an immediately enforced uniqueness,
   foreign-key, or check constraint to existing writes, or reinterpret an
   existing value.
2. **Migrate:** move data with a bounded, observable, restartable operator
   command. Alembic may perform only small deterministic transformations that
   fit inside the protected migration window.
3. **Switch:** deploy the canonical read/write path and prove backfill and data
   invariants. If an old application still needs the old representation, any
   temporary dual write stays inside the owning infrastructure adapter.
4. **Contract:** in a later release, remove the retired structure and advance
   `minimum_compatible_application_revision`. Confirm a recoverable database
   point, completed backfill, drained old work, and a successfully deployed
   application at or above the new floor before approval.

Production never runs Alembic downgrade as application rollback. The release
workflow may deploy an older immutable application only when its schema
revision is in the live range from `minimum_compatible_application_revision`
through the current migration head. Repair after a migration failure is a
forward fix or an explicitly approved database recovery operation.

## Keeping compatibility code bounded

- HTTP version adapters live in `server/app/transport/http`; MCP adapters live
  in `server/app/transport/mcp`; storage overlap lives in the owning module's
  infrastructure adapter. Domain and application use cases expose only the
  current model.
- `web/` consumes one generated contract and never guesses whether a response
  is old or new. Server adapters translate old public shapes to the canonical
  use case.
- Job changes are consumer-first: consumers accept both envelopes before
  producers emit the new one. A queued accepted job remains executable.
- Compatibility behavior is registered in
  `server/contracts/deprecations.json` with its owner, replacement, dates, and
  low-cardinality telemetry key. Do not add an unowned alias, global fallback,
  indefinite feature flag, or duplicated business implementation.

Each registry entry contains a canonical `id`, its `boundary`, exact `target`,
`owner`, `replacement`, `deprecated_on`, `earliest_removal_on`,
`telemetry_key`, nullable `zero_traffic_since`, lifecycle `state`, nullable
`removed_on`, and nullable `removal_evidence`. An HTTP target is one complete
`METHOD /api/v1/path` operation and an MCP target is one complete tool; field-
level breaking changes never receive a retirement waiver.

Dates use ISO `YYYY-MM-DD`; the earliest removal date must be at least 90 days
after deprecation. Reset `zero_traffic_since` to null whenever traffic recurs.
A new entry must start in the `deprecated` state. A later removal change sets
`state` to `removed` and records both `removed_on` and a reviewable evidence
reference. CI permits the exact operation or tool to leave its snapshot only
after 30 complete zero-traffic days; it rejects direct-to-removed entries and
changes to the immutable identity of an existing entry. Keep the removed entry
as a tombstone so the identifier, telemetry key, and evidence are not silently
reused or forgotten.

HTTP or MCP deprecation remains available for at least 90 days after notice and
may be removed only after its production telemetry has shown zero calls for 30
consecutive days. Removal happens at the version/tool boundary; it does not
leave a second domain model behind.

## Required evidence

- OpenAPI and MCP snapshots change with their source and pass merge-base
  compatibility checks.
- Migration history is byte-immutable, policy-complete, and a prefix of the
  candidate release contract.
- Database CI proves empty-to-head, base-to-candidate with retained data, and
  repeated upgrade convergence.
- A contract migration includes backfill invariants, the new compatibility
  floor, recovery evidence, and an application smoke test against the
  candidate schema.
- The pull request records rollout, rollback, documentation impact, and the
  exact checks performed.
