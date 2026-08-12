# Reader experience

Reader is the document-focused surface for one Library paper. It owns PDF
navigation, selection, annotations, document details, and the paper-scoped
conversation entry point. It does not own a second conversation protocol or a
second Workspace shell.

The active desktop acceptance source is Figma
[`50 — Reader`](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=390-2).
The canonical conversation boundary is
[`Reader conversation contract v2`](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=910-2).

## Product boundary

- The route is `/reader/[documentId]`.
- Library is the only paper collection. Opening a Library paper enters Reader;
  Reader does not create another paper record or another Library membership.
- Reader uses the shared conversation experience. Home owns message rendering,
  ordered stream reduction, Worklog, final-answer actions, suggestions, and the
  Sources panel. Reader contributes paper, page, selection, and annotation
  context through explicit adapter props.
- Opening a paper does not create a conversation. `New chat` enters a local
  blank state and the paper-scoped conversation is created by the first send.
- Translation and project collaboration are outside this release. Existing
  design affordances identify them as unavailable and never navigate to an
  empty route.

## Layout contract

Desktop Reader is an application viewport rather than a scrolling marketing
page. The Workspace navigation is a collapsed rail, the PDF canvas is the
primary region, and the contextual panel is secondary. Toolbars and panels may
be sticky inside their own regions, but the document shell must not make the
browser body scroll.

Reader has four independently scrollable regions where applicable:

1. page thumbnails;
2. the PDF page canvas;
3. the active contextual panel;
4. the paper-conversation list disclosure.

At 320, 390, and 430 CSS pixels, Reader becomes an immersive document surface:

- the Workspace bottom navigation is absent;
- the top bar contains Back to Library, a truncated paper title, and document
  tools;
- the PDF remains visible as the primary surface;
- Ask, Annotations, Details, Search, and Outline open as full-height bottom
  panels with safe-area padding;
- dismissing a panel preserves page, zoom, search result, draft, selection, and
  active conversation;
- the soft keyboard resizes the active panel without moving document controls
  underneath the keyboard.

Desktop columns must never be compressed into a narrow three-column layout.
The breakpoint changes the information architecture, not only widths.

## URL and local state

The URL is the shareable reading state:

- `page`: one-based current PDF page;
- `panel`: `ask`, `annotations`, `details`, `search`, `outline`, or omitted;
- `conversation`: the active paper-scoped conversation ID, or omitted for the
  local blank state.

Zoom, fit mode, search query, search match index, draft text, temporary
selection, open annotation editor, and panel animation state are local. Invalid
page and conversation parameters are normalized after the document metadata is
known and must not produce a second history entry.

## PDF surface

Reader uses the official `pdfjs-dist` Display and Viewer layers through the
feature-owned `PdfDocumentAdapter`. The worker and main package versions must
match. PDF code loads on the client and must not enter the server-rendering
bundle.

The initial surface supports:

- one primary rendered page with previous/next and direct page input;
- lazy page thumbnails;
- zoom in/out, fit width, and fit page;
- PDF text search with result count and previous/next traversal;
- PDF outline navigation and an explicit no-outline state;
- download URL refresh exactly once when a signed URL expires;
- Canvas, Text, and Annotation layers without mutating the source PDF.

Search hits, selections, and annotations are overlays derived from normalized
anchors. They are never burned into the PDF. A damaged, encrypted, unavailable,
processing, failed, or unauthorized document receives its own terminal state;
these states do not masquerade as an empty PDF.

## Selection and annotations

The text-selection toolbar contains only Ask, Highlight, Note, and Copy. All
four actions use the shared control-state and feedback rules.

- Ask opens the Ask panel and adds a removable context chip; it never sends
  automatically.
- Highlight creates a private highlight by default and may be recolored or
  deleted by its owner.
- Note creates or edits a highlight thread and supports comment creation,
  editing, and deletion subject to server capabilities.
- Copy reports success through the shared copied state and remains keyboard
  accessible.

Annotation rows and PDF overlays share a single active annotation ID. Choosing
either representation navigates to and emphasizes the other. A persisted PDF
anchor uses one-based page numbers and zero-to-one normalized rectangles.

## Paper conversations

Reader lists only conversations whose scope is the current paper. The list may
be searched, pinned, switched, or replaced with a local new-chat state. Scope
filtering and authorization happen on the Server; the Web must not fetch global
conversations and filter them locally.

When a selected passage is sent, the turn context contains the document ID,
page number, selected text, and PDF anchor. A selected annotation is represented
by its thread ID. These contexts are persisted with the turn so a historical
message can restore its reading location.

The shared conversation contract remains unchanged:

- ordered streaming and Worklog during execution;
- `response_ready` as the persisted answer boundary;
- optional turn suggestions in the same stream;
- identical retry, variant, copy, source, and suggestion behavior;
- a single responsive Sources panel.

Current-paper sources navigate inside the open document. Other paper sources
open that paper's Reader route. External sources open a new browser tab.

## Details

Details presents only canonical document data: title, authors, abstract, DOI,
journal or venue, publication date, file information, parsing status, and
quality. Missing values use explicit unknown or unavailable copy rather than
invented metadata. Project membership, collaborative sharing, and Translation
remain unavailable until their owning features exist.

## Acceptance matrix

Every reusable Reader component needs Storybook coverage and the route needs
Playwright coverage for the following matrix:

| Surface | Required states |
| --- | --- |
| Document | loading, ready, processing, failed, unauthorized, unavailable, damaged, encrypted |
| Navigation | first page, middle page, last page, direct page input, fit width, fit page, zoomed |
| Search and outline | closed, query with no result, one result, multiple results, no outline, nested outline |
| Selection | selected, Ask context, color menu, note editor, copied, cancelled |
| Annotations | empty, populated, selected, editing, deleting, permission denied |
| Ask | local new chat, streaming, response ready, suggestions delayed, historical, retried variants, source open |
| Conversations | loading, empty, populated, searched, pinned, active, local new chat |
| Responsive | desktop, 320, 390, 430, soft keyboard, safe area, reduced motion |
| Appearance | Light, Dark, English, Simplified Chinese, long title, narrow content |

Figma frame names and Storybook story names use the same state terms. Obsolete
Reader conversation-only mocks and any duplicated answer UI stay archived and
are not acceptance sources.
