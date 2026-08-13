# 0013 — Reader context and anchor contracts

Status: Accepted
Date: 2026-08-12
Owners: Scholens

Reader annotation naming, audience, and collaboration lifecycle are superseded
by [ADR 0014](./0014-annotation-thread-collaboration.md). The typed anchor and
conversation-cursor decisions below remain accepted.

## Context

Reader must restore a selected PDF passage, navigate from an annotation to its
exact page region, and limit conversation history to one paper. The previous
turn payload used loosely shaped reference dictionaries and separate highlight
identifiers, while Research positions accepted arbitrary JSON. Those shapes
could drift between streams, history, annotations, and PDF rendering.

## Decision

- A turn owns one ordered list of discriminated `contexts`: either a
  `paper_selection` with document, page, text, and normalized PDF anchor, or a
  `highlight_thread` identifier. The former loose turn fields are removed.
- Research positions are a discriminated union. `pdf_text` stores one-based
  page numbers and normalized rectangles; `parsed_text` stores validated text
  offsets and an optional page.
- `GET /conversations` accepts a matching `scope_type` and `scope_id`. Its
  signed cursor includes those filters and cannot be replayed across papers.
- New and imported highlight threads are private by default.
- These are pre-release replacement contracts. No compatibility properties,
  aliases, dual writes, or legacy position decoders remain.

## Alternatives considered

Keeping arbitrary dictionaries was rejected because malformed geometry would
fail only in the renderer. Browser-side conversation filtering was rejected
because it leaks unrelated metadata and makes authorization a UI concern.
Duplicating selections into prompt text was rejected because display,
persistence, and Agent context would have separate sources of truth.

## Consequences

Reader, Home, Server, OpenAPI fixtures, and tests use the same generated union.
PDF geometry is viewport-independent. New anchor kinds require an intentional
union extension, and clients cannot reuse a cursor for another scope.

## Validation

Server tests reject invalid rectangles, spans, selection pages, and cross-scope
cursor replay. OpenAPI checks prove the loose fields are gone. Reader tests
restore persisted selections and navigate highlights at multiple widths.
