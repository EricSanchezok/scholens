# 0046 — Keep persisted Reader annotations out of text selection hit testing

Status: Accepted
Date: 2026-09-03
Owners: Reader team

## Problem

The PDF Reader paints persisted highlights and annotation underlines above the
PDF.js text layer. Rendering each painted rectangle as a focusable button means
the browser targets that button instead of the text layer when a drag begins
inside an existing annotation. The document selection controller therefore
never receives the pointer gesture, and readers cannot select text for
translation, Ask, or a new annotation. Multi-line anchors also create repeated
focus stops for one logical thread.

## Decision

Persisted annotation fills and underlines are decorative, pointer-transparent
background layers. They render as non-interactive elements in an `aria-hidden`
paint layer with no click handlers, focus state, or control affordances. The
PDF.js text layer remains the sole owner of native text selection, including
selections that begin inside or cross an existing annotation.

Commented annotations retain one interactive page-edge comment-count marker.
The Annotations panel remains the entry point for pure highlights and continues
to provide selection, navigation, recoloring, and deletion. Existing active
selection and reflow source overlays remain pointer-transparent, and PDF.js
links retain their existing annotation-layer behavior.

When highlight creation is asynchronous, the Reader records the submitted
selection's stable key. A successful response clears the active selection only
if that key is still current; a newer selection is never removed by an older
request, and a failed request leaves the current selection available for retry.

## Alternatives considered

- Keep rectangle buttons and stop propagation during drag. This still leaves
  overlapping controls in the hit-test and focus order, and touch and keyboard
  behavior would remain ambiguous.
- Guess whether a pointer gesture is a click or drag using a time or distance
  threshold. Thresholds vary across browsers, pointer types, and assistive
  input, making selection unreliable.
- Add an explicit selection/annotation mode switch. This increases cognitive
  and keyboard cost and creates a mode that can be left on accidentally.
- Make the whole annotation layer pointer-transparent, including comment
  controls. That would remove the useful in-document entry point for threads;
  only the page-edge count marker is interactive.

## Consequences

Readers can select, translate, ask about, and annotate text without first
clearing existing highlights. Persisted visual state no longer contributes
duplicate tab stops or misleading hover affordances. Thread opening is
deliberately available through comment markers and the panel, so clicking
painted text itself is no longer a supported interaction. No backend fields,
public API types, migrations, or PDF.js responsibilities change.

## Validation

Reader Playwright coverage verifies that paint rectangles are not buttons, have
`pointer-events: none`, resolve through `elementFromPoint` to the PDF text
layer, and support a real mouse drag started within a persisted highlight.
Discussion tests open through the comment marker, while panel tests retain the
pure-highlight path. Unit coverage verifies stable selection identity, and the
full Web gate remains the release check.
