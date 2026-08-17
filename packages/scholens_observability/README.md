# scholens-observability

`scholens-observability` provides business-agnostic diagnostics shared by
Server and Jobs: scoped context, structured logging, low-cardinality metrics,
OpenTelemetry setup, custom spans, and bounded diagnostic snapshots.

## Contract and limits

- Observability context is diagnostic metadata only and must never authorize a
  request or operation.
- Callers project business objects into safe scalar fields. Arbitrary values,
  credentials, raw provider payloads, and sensitive URLs are not log data.
- Metric attributes remain low-cardinality; entity IDs belong in traces or
  diagnostic context rather than metric dimensions.
- Snapshot persistence is best effort and bounded. Product behavior must not
  depend on telemetry delivery.
- Snapshot writers use a caller-owned prefix that must match the workload's
  object-storage policy. Write failures expose only the originating snapshot
  identity and allowlisted provider error fields; exception messages and
  storage coordinates are never emitted.
- Server and Jobs own instrumentation composition and lifecycle. This package
  does not import either application.

The supported public surface is exported from `scholens_observability`. The
package is typed and ships `py.typed`; direct tests live in `tests/` and run
through the workspace described in [`../README.md`](../README.md).
