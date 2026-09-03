# 0046 — Agent-native annotation anchors and render isolation

Status: Accepted
Date: 2026-09-03
Owners: Scholens

## Problem

An agent usually has reliable paper text but not PDF.js viewport geometry.
Requiring `pdf_text` rectangles made MCP annotation calls brittle and caused
failed or invisible marks when offsets, quote text, and geometry drifted apart.
In the Reader, annotation hover and mutation state also shared the parent
render path with PDF.js canvas and text-layer work. Each unstable callback or
list refresh could cancel a render, clear the text layer, and visibly flash the
document.

## Decision

Expose `annotate_paper` as the default MCP write path. It accepts a document,
exact quote, optional comment, color, audience, and optional paper-content
digest. The Server normalizes Unicode/whitespace, resolves exactly one match
against the authorized canonical text, and persists a `parsed_text` position.
Not-found, ambiguous, unavailable, and stale-digest cases fail before any
write with bounded actionable details. The response includes the stable thread
URI, compact resolved anchor, and whether the Reader paints a fill or underline.
The existing geometry-first `create_annotation_thread` remains available for
advanced clients and advertises the replacement.

The Reader resolves `parsed_text` anchors only after PDF.js has rendered a page.
It maps the immutable quote through DOM text nodes to normalized page
rectangles, reusing the same selection-rectangle validation as user selection.
If no match is found, it paints nothing rather than guessing. Existing
`pdf_text` anchors and exact-anchor grouping remain unchanged; comment-free
threads use a color fill and commented threads use a colored underline.

PDF.js render effects receive stable callback identities and callback refs, so
hover, selection, panel state, and annotation-list updates can re-render the
overlay without cancelling the canvas/text-layer render. Annotation queries
retain the previous list while invalidated data refetches, and the panel stays
mounted while its selection editor resets only when the semantic selection
changes.

## Alternatives considered

- Require every agent to provide PDF rectangles. Rejected because agents can
  reliably quote canonical paper text but cannot safely reconstruct the
  browser's PDF.js viewport geometry.
- Fuzzy-match the nearest passage and always paint it. Rejected because an
  ambiguous or stale quote would create a misleading scholarly record.
- Remount the entire Reader after each annotation update. Rejected because it
  cancels PDF.js work, clears the text layer, and produces the observed flash;
  overlay state can be updated independently.

## Consequences

Agents can annotate from paper evidence without reconstructing browser
coordinates, and stale or ambiguous writes are explicit recovery points. A
parsed anchor may remain temporarily unresolved on a page whose PDF text layer
does not expose the same extraction; the UI intentionally leaves it unpainted
and the thread remains readable in the panel. The client carries a small
ephemeral resolver cache in component state; no persistence migration is
needed. Render isolation reduces PDF.js cancellations but does not change the
existing ten-second focused-panel collaboration poll.

## Validation

- Resolver unit tests cover normalized whitespace, ambiguity, and not-found
  errors.
- Reader tests retain fill/underline and duplicate-anchor behavior; parsed
  anchor DOM mapping is covered by the resolver's browser test path.
- MCP contract export and catalog tests cover the new typed tool and 64-tool
  fully-authorized profile.
- Server, MCP connector, Web, and documentation gates remain required before
  merge.
