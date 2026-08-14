# 0011 — Library projections and signed keyset pagination

Status: Accepted
Date: 2026-08-11
Owners: Scholens

## Problem

Library needs a personal Papers collection and a cross-scope Outputs collection.
The existing Figma pagination implied page numbers, while the Server needs
stable navigation as papers and Research items are added or updated. The Web
must not combine Project, Paper, and personal Research endpoints and guess
permissions. The product is pre-release, so retaining the old URL-ingestion
contract would create two authorities without serving a released client.

## Decision

Papers remain personal `LibraryPaper` memberships. Outputs are a Server-owned
projection over visible `ResearchItem` rows in personal, document, and Project
scopes, limited to the four kinds that already exist. The projection includes
source scope and source title so the Web performs no permission join.

Both collections use opaque HMAC-signed keyset cursors. A cursor binds the user,
collection, normalized query, filters, sort, and limit and carries a stable UUID
tie-breaker. APIs return Previous and Next cursors plus a total count; offset
pagination and page-number emulation are excluded.

The old `/paper-ingestions/urls` route is replaced by one discriminated
`/paper-ingestions/sources` request for DOI, arXiv, or a direct PDF URL. Failed
ingestion retries create a new durable job from the persisted source. Personal
paper removal removes membership only and schedules orphan cleanup through the
existing lifecycle.

## Alternatives considered

- Join Outputs in the Web. Rejected because it duplicates permission policy,
  adds race conditions, and leaks module ownership into presentation code.
- Use offsets while calling them cursors. Rejected because inserts and updated
  sort keys cause skips and duplicates and because the token would not be a
  stable continuation contract.
- Keep the old URL route beside the source union. Rejected because the product
  is unreleased and dual protocols would become avoidable compatibility debt.
- Create Report or Note output kinds to match an old mockup. Rejected because
  design must represent the domain, not invent persistence models.

## Consequences

The bootstrap layer owns the only cross-module output projection. Every new
sort needs a deterministic keyset and UUID tie-breaker. Filter or sort changes
invalidate existing cursors by design. Clients use explicit Previous/Next
navigation and clear selection when the collection identity changes.

## Validation

Server tests cover cursor binding and bidirectional navigation, permissions and
deduplication, source normalization and PDF failures, retry ownership/status/
idempotency, and membership-only removals. Public OpenAPI contains only the new
source contract. Web tests cover URL restoration, responsive collections, and
the absence of dead links for unfinished Reader or Projects dependencies.
