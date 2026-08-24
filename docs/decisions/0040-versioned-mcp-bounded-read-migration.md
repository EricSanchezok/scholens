# 0040 — Versioned migration for bounded MCP reads

Status: Accepted
Date: 2026-08-24
Owners: Scholens

## Problem

ADR 0038 requires bounded public projections, but applying those projections by
changing an existing tool's input or output schema would break deployed MCP
clients. Six established reads already have public contracts: `get_paper`,
`get_library_paper`, `get_annotation_thread`, `get_research_output`,
`list_library_papers`, and `list_research_outputs`. Their complete-object
responses can exceed an Agent's context budget, while the durable Job contract
can contain worker payloads and storage implementation details that must not
cross the MCP boundary.

The research-output contract also had a pre-existing closure defect. Its shared
kind enum advertised annotation threads, an explicit annotation filter was
rejected, the default Library branch could still return annotations, and the
corresponding get tool refused them. Preserving that contradiction would keep
old clients parseable but not usable.

## Decision

Keep the six established tools registered and keep their legacy input and
output shapes. Their runtime branches remain available:

- `get_paper`, `get_library_paper`, `get_annotation_thread`, and
  `get_research_output` return the complete historical response model;
- `list_library_papers` retains its full historical page size, paper/ingestion
  union, and response model;
- `list_research_outputs` retains its Library, Project, and paper branch
  projections, including the historical `LibraryOutputResponse` wrapper where
  that branch used it;
- the list kind bound expands additively from three to four, explicit and
  default filters accept all four stored kinds, and `get_research_output` reads
  annotation threads so every listed item has a matching get operation.

Add bounded replacement tools instead of narrowing those contracts:

| Legacy tool | Replacement | Replacement contract |
| --- | --- | --- |
| `get_paper` | `get_paper_page` | Lossless UTF-8 pages of canonical metadata JSON |
| `get_library_paper` | `get_library_paper_page` | Lossless UTF-8 pages of personal Library and canonical document JSON |
| `get_annotation_thread` | `get_annotation_thread_page` | Lossless UTF-8 pages of canonical thread JSON |
| `get_research_output` | `get_research_output_page` | Lossless UTF-8 pages of canonical output JSON |
| `list_library_papers` | `list_library_paper_summaries` | Cursor-paginated bounded durable-paper previews |
| `list_research_outputs` | `list_research_output_summaries` | SQL-projected, cursor-paginated bounded summaries |

MCP Resources point to the bounded replacements. The legacy names are recorded
in `server/contracts/deprecations.json` with an owner, replacement, unique
telemetry key, a minimum 90-day support window, and the normal 30-day zero-
traffic removal evidence requirement.

For Job tools, retain the established `JobResponse`, `JobListResponse`, and
waitable response schemas, including the parseable `result: object | null`
union. The MCP projector always emits `result: null`, status queries do not load
the durable result column, and legacy invocation replays pass through the same
projector. This runtime-only redaction is an approved emergency security
correction: allowing an internal result to continue crossing the boundary is
not a compatibility guarantee. The incident record documents impact,
authorization, and follow-up.

## Alternatives considered

- Narrow the established schemas in place. Rejected because response paging
  and summary records are different contracts, not compatible constraints on
  the old contracts.
- Add an `anyOf` legacy/new response under each old name. Rejected because a
  caller could not reliably select or interpret one deterministic operation.
- Preserve the three-kind annotation contradiction exactly. Rejected because
  it violates list-to-get closure; accepting the fourth existing enum value is
  additive and makes the established surface coherent.
- Keep Job result objects and redact known keys. Rejected because new internal
  fields would become public by default and nested payloads cannot be secured
  by a deny-list.

## Consequences

The catalog grows by six tools during migration, and documentation must label
legacy and replacement behavior precisely. Existing clients continue parsing
their known operations; new clients and all Resource continuations use bounded
operations. Legacy complete-object calls can still fail the global output
budget when historical data is unusually large, in which case the stable
budget error directs callers to the replacement rather than silently dropping
fields.

`update_library_paper` is the sole write-path exception: its established result
fields remain present as an explicitly bounded preview and its action is a
compact receipt. This prevents an otherwise valid write from being rolled back
because a historical metadata echo exceeds the MCP envelope budget. The
`content_truncated` flag and guidance make the loss visible, and
`get_library_paper_page` closes the lossless read path.

Removal is a later contract operation, not part of this change. It requires the
registry date, telemetry, evidence, compatibility checks, and release review
defined by the contract-evolution policy.

## Validation

- Contract governance asserts that every old and replacement name exists and
  that all six deprecations are owned and time-bounded.
- Legacy branch tests cover Library, Project, and paper shapes plus default and
  explicit annotation filters and list-to-get closure.
- Paging tests reassemble canonical JSON losslessly and reject stale or
  cross-resource cursors.
- Job tests validate the legacy schema union, null runtime projection, legacy
  replay sanitation, status-only SQL selection, and complete `CallToolResult`
  byte budgets.
- Merge-base compatibility runs against a temporary generated contract before
  the reviewed snapshot is exported.
