# 0027 — Project uploads default to the personal Library

Status: Proposed
Date: 2026-08-18
Owners: Scholens

## Problem

A user who uploads a paper into a Scholens Project through the MCP surface
(`ingest_paper` with a bound `project_id`) only receives a `ProjectPaper`
membership. The paper never appears in the user's personal Library unless the
Agent separately calls `collect_project_paper_to_library`. Production evidence
showed a project-uploaded paper ("CWM: An Open-Weights LLM...") invisible in
`/library`, which contradicts the user's mental model that uploaded papers
belong to the user and Projects are just an organization layer over them.

The Web "Add papers" flow already uploads into the personal Library only;
Project membership is chosen afterwards from Library papers. The MCP/Project
direct-upload path is the only surface where an uploaded paper can end up
with no personal membership.

## Decision

Every paper ingestion defaults to also creating the uploader's personal
`LibraryPaper` membership, in the same atomic ingestion transaction, while
keeping the `ProjectPaper` membership as an independent idempotent
association. Callers can opt out per ingestion with `add_to_library=false`
(requires a `project_id`) to keep the historical Project-only behavior.

Concretely:

- `PreparePaperUploadRequest`, `PaperIngestionRequest` (HTTP), and
  `IngestPaperInput` (MCP) gain `add_to_library: bool = true`.
- `finalize_reserved_document` always attaches the personal Library
  membership first (when `add_to_library` is true), then attaches the Project
  membership when a Project is targeted. Both attachments are idempotent and
  recorded independently as `reference_created_library` and
  `reference_created_project` on the reservation, replacing the single
  `reference_created` boolean.
- Failure and cancellation compensation deletes only the membership(s) this
  job actually created, never a pre-existing membership of the same user.
- Billing: the Project side continues to bill the Project owner. The uploader
  is billed for the personal-Library side only when they do not already own
  the Document (account-unique union), which means an owner uploading to
  their own Project is never double-charged. A collaborator uploading to
  someone else's Project with `add_to_library=true` reserves one personal
  Library slot on their own account.
- Retries inherit the original job's `add_to_library`; Project ownership
  transfer never moves the library-side billing owner.
- Existing Project-only papers are not backfilled. Users collect them
  explicitly with the existing collect tool.

## Alternatives considered

- **Library list as a union of all accessible Project papers (view-only
  merge).** Rejected: breaks the personal-`LibraryPaper` membership boundary
  and entangles permissions, GC reference counting, and quota projection.
- **Always add to Library with no opt-out.** Rejected: a collaborator
  uploading into someone else's Project would be forced into a personal quota
  charge with no way to contribute Project-only material.
- **Creating the personal membership only at collect time (status quo).**
  Rejected: does not fix the user-visible gap and leaves the MCP surface
  inconsistent with the Web upload path.
- **Storing `add_to_library` in the job payload JSON.** Rejected: billing and
  retry need a typed, indexed column.
- **Adding a generic billing line table for the second charging side.**
  Rejected as over-generalization; three library-side columns on the
  reservation express the one additional billing axis needed today.

## Consequences

- Uploaded papers now appear in the uploader's personal Library by default on
  every surface (Web, HTTP, MCP, Zotero), matching the product mental model
  that Projects organize papers the user owns.
- `add_to_library=false` preserves the Project-only workflow for collaborators
  who deliberately contribute without collecting.
- Quota semantics change for collaborators: uploading into another user's
  Project with `add_to_library=true` consumes one slot of the uploader's own
  paper/storage quota. This is the same accounting as the previous
  "upload + explicit collect" sequence, now atomic.
- Reservation records carry two independent reference-created flags, so
  failure/cancellation compensation is precise and never deletes a user's
  pre-existing membership.
- Schema evolves in two phases (expand + contract) per ADR 0026; the
  contract phase retires the `reference_created` column and advances the
  minimum compatible application revision.
- Existing Project-only papers remain Project-only; no backfill is performed.

## Validation

- Server unit tests cover: personal upload attaches Library only; Project
  upload with default attaches both; `add_to_library=false` attaches Project
  only and skips library billing; `add_to_library=false` without a Project is
  rejected; collaborator library-side billing; owner self-upload is not
  double-charged; transfer preserves library-side billing owner; failure and
  cancellation compensation deletes only job-created memberships; retries
  inherit `add_to_library`.
- Contract snapshots (OpenAPI + MCP) are regenerated and include
  `add_to_library` with default `true`; web generated types compile.
- `alembic check` and the migration-policy compatibility script pass for the
  expand/contract pair.
