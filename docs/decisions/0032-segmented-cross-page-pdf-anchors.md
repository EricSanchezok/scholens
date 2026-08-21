# 0032 — Segmented cross-page PDF anchors

Status: Accepted
Date: 2026-08-21
Owners: Scholens

This record amends the one-page `pdf_text` geometry described by
[ADR 0013](./0013-reader-context-and-anchor-contracts.md). Its other context and
cursor decisions remain accepted.

## Problem

A browser Selection can cross PDF.js text layers and can expose more than one
Range. Reader previously installed one commit controller per page. When a drag
crossed a page boundary, no controller owned both endpoints, so an earlier
page's cached Range could be committed after pointer-up. That revived stale
geometry and realigned the document to the earlier page.

The product also needs Ask, translation, copy, highlights, notes, and Project
discussions to refer to the same exact cross-page quote. Splitting one gesture
into unrelated annotation threads would lose that identity and make discussion
and deletion semantics ambiguous.

## Decision

- Reader owns one document-level selection controller. It reads every native
  Range, retains the browser's exact selected text, clips geometry to each
  intersected PDF text layer, normalizes rectangles per page, and commits one
  ordered selection.
- A `pdf_text` position may carry ascending, unique `segments`, each containing
  one page number and its normalized rectangles. `page_number` and `rects`
  remain required and must equal the first segment. Requests without segments
  remain valid one-page anchors.
- The materialized annotation `page_number` remains the first segment's page,
  so existing source ordering, indexes, and navigation contracts do not need a
  migration. The complete position stays in the existing JSON value.
- One segmented position belongs to one AnnotationThread or one turn context.
  Every selected-text action consumes that same logical selection.
- The UI paints all page segments. The selection toolbar follows the native
  focus end; direct interaction with a later persisted segment opens the thread
  in place, while explicit navigation from the annotation rail targets the
  first segment.

## Alternatives considered

Keeping one controller per page and merging its outputs was rejected because
controllers race over browser-global Selection state and cannot reliably
distinguish a transient collapse from another page's valid Range. Persisting a
thread per page was rejected because one user gesture would acquire multiple
audiences, colors, comment timelines, and deletion lifecycles. Replacing the
position with only a new segment array was rejected because it would break the
published API and existing stored positions.

## Consequences

Old and new clients remain interoperable without a database migration. All
consumers must read PDF geometry through the canonical segment adapter rather
than assuming `rects` describes every painted page. The compatibility
projection is deliberately duplicated at the transport boundary and validated
there; application behavior uses a single canonical segment view.

## Validation

Server contract tests accept legacy and segmented positions and reject
unordered, duplicate, or mismatched projections. Reader unit tests cover exact
cross-page text, per-page geometry, transient collapse, and stale-selection
rejection. A focused Reader browser test runs in Chromium, Firefox, and WebKit,
persists one two-page highlight, and verifies both page overlays.
