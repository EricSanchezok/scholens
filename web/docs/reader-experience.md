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
- Reader uses the shared conversation experience. `features/conversation` owns
  message rendering, ordered stream reduction, Worklog, final-answer actions,
  suggestions, Sources, and the Composer surfaces used by both Home and Reader.
  Reader contributes paper, page, selection, and annotation context through
  explicit adapter props.
- Opening a paper does not create a conversation. `New chat` enters a local
  blank state and the paper-scoped conversation is created by the first send.
- Translation and project collaboration are outside this release. Existing
  design affordances identify them as unavailable and never navigate to an
  empty route.

## Layout contract

Desktop Reader is an application viewport rather than a scrolling marketing
page. After the collapsed Workspace rail, Reader contains two independently
owned, top-aligned work regions:

1. the document region, whose toolbar combines Back to Library, the truncated
   paper identity, page controls, view controls, and document actions above the
   thumbnail rail and PDF canvas;
2. the contextual region, whose equally tall toolbar contains Ask,
   Annotations, Details, and Collapse above the active panel.

Reader must not add a full-width paper title row above these regions or a
separate Ask button outside the contextual panel. The panel width is responsive
between 23rem and 31.25rem so it remains secondary to the PDF without turning
conversation content into an unreadably narrow strip. Toolbars and panels may
be sticky inside their own regions, but the document shell must not make the
browser body scroll.

Reader has four independently scrollable regions where applicable:

1. document navigation, showing either page thumbnails or the PDF outline;
2. the continuous PDF document canvas;
3. the active contextual panel;
4. the paper-conversation list disclosure.

Search is not a fifth panel. On desktop and mobile it temporarily replaces the
document toolbar controls with a compact query field, result position, and
previous/next controls. The PDF remains visible and interactive while search is
active. On desktop, one toggle in the document toolbar switches the left
document-navigation region between page thumbnails and Outline. Its icon and
accessible name always describe the destination state; it never opens a modal
or obscures the document.

At 320, 390, and 430 CSS pixels, Reader becomes an immersive document surface:

- the Workspace bottom navigation is absent;
- the top bar contains Back to Library, a truncated paper title, and document
  tools;
- the PDF remains visible as the primary surface;
- Ask, Annotations, and Details open as full-height bottom panels with safe-area
  padding;
- Search remains in the compact document toolbar, while Outline uses a
  full-height document-navigation panel because the thumbnail rail is absent;
- dismissing a panel preserves page, zoom, search result, draft, selection, and
  active conversation;
- the soft keyboard resizes the active panel without moving document controls
  underneath the keyboard.

Desktop columns must never be compressed into a narrow three-column layout.
The breakpoint changes the information architecture, not only widths.

## URL and local state

The URL is the shareable reading state:

- `page`: one-based current PDF page;
- `panel`: `ask`, `annotations`, `details`, or omitted;
- `conversation`: the active paper-scoped conversation ID, or omitted for the
  local blank state.

Zoom, fit mode, desktop document-navigation mode, mobile Outline disclosure,
search disclosure, search query, search match index, draft text, active browser
selection, pending turn context, annotation editor state, and panel animation
state are local. Invalid page, panel, and conversation parameters are
normalized after the document metadata is known and must not produce a second
history entry.

## PDF surface

Reader uses the official `pdfjs-dist` Display and Viewer layers through the
feature-owned `PdfDocumentAdapter`. The worker and main package versions must
match. PDF code loads on the client and must not enter the server-rendering
bundle.

The document surface supports:

- continuous vertical page scrolling with lazy nearby-page rendering;
- viewport-driven current-page updates in the URL, while previous/next,
  thumbnails, outline destinations, search results, and direct page input
  scroll the same document surface;
- icon-only page controls retain their footprint at the first and last page,
  but express the unavailable direction with a muted icon and no filled block;
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

Selection has three deliberately separate lifetimes:

- `activeTextSelection` captures the normalized transient selection, renders
  its post-pointer overlay, and solely controls the floating toolbar;
- `pendingTurnContext` is the immutable selection snapshot committed to the Ask
  Composer;
- `annotationSelection` is the selection snapshot being edited in Annotations.

The text-selection toolbar is absent until a real non-collapsed PDF text
selection exists. It chooses the side with usable space, remains above the PDF
page stack when it crosses a page gap, and stays horizontally clamped to the
rendered page. It contains only the Iconoir icons for Ask, Highlight, Note, and
Copy; accessible names live in tooltips and `aria-label`s rather than visible
action text. All four actions use the shared control-state and feedback rules.

While the pointer is down, the PDF text layer uses the dedicated translucent
blue document-selection token. The original Canvas text must remain legible
through the selection, matching the familiar line-by-line treatment of desktop
research readers rather than placing an opaque wash over the page. After
pointer-up, Reader replaces the browser-native selection with a normalized
overlay using the same token. The browser selection is cleared before this
overlay appears. Reader preserves PDF.js' complete TextLayer positioning
contract so the selectable browser glyphs stay aligned with the Canvas glyphs;
page-sized and out-of-page browser rectangles are rejected rather than clamped
into false highlights. Overlapping PDF text fragments on the same visual line
are coalesced, and the remaining geometry is painted once so translucent color
can never accumulate into darker stripes. The overlay remains visible with the
floating toolbar until the user acts, presses Escape, clicks elsewhere, or
moves to another page.

- Ask copies the selection into `pendingTurnContext`, opens Ask, clears the
  browser selection, and adds a removable page chip; it never sends
  automatically.
- Highlight first discloses the adjacent color palette, creates a private
  highlight, then clears the browser selection. It may be recolored or deleted
  by its owner.
- Note copies the selection into `annotationSelection`, opens the annotation
  editor, then clears the browser selection. Threads support comment creation,
  editing, and deletion subject to server capabilities.
- Copy reports success through the shared copied state, remains keyboard
  accessible, and dismisses the toolbar after feedback.
- Clicking outside, Escape, page navigation, or a replacement selection clears
  only `activeTextSelection`; committed Ask and annotation contexts remain.

Annotation rows and PDF overlays share a single active annotation ID. Choosing
either representation navigates to and emphasizes the other. A persisted PDF
anchor uses one-based page numbers and zero-to-one normalized rectangles.
The empty Annotations panel is a quiet typographic prompt without a decorative
list icon; the panel tab already provides the necessary context.

## Paper conversations

Reader lists only conversations whose scope is the current paper. Ask begins
with a compact, borderless current-conversation switcher and a separate New chat
icon. The
search field and grouped Pinned/Recent list exist only while the switcher is
open; they are not a permanent row or horizontal pill strip. New chat remains a
local draft until the first send. Scope filtering and authorization happen on
the Server; the Web must not fetch global conversations and filter them
locally.

The Ask message viewport and Composer are two siblings inside the contextual
panel. Messages own the panel's vertical scroll, while the `context-panel`
Composer remains docked at the bottom with its input on top and context,
reasoning, and send controls below. The switcher, message viewport, and Composer
are separated by spacing rather than stacked card borders; the Composer uses
the same floating rounded treatment as Home at the narrower panel measure.
Side-panel presentation may change measure, spacing, and docking, but it must
reuse the same message, Worklog, answer, source, suggestion, retry, and variant
components as the workspace layout.

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

| Surface            | Required states                                                                                           |
| ------------------ | --------------------------------------------------------------------------------------------------------- |
| Document           | loading, ready, processing, failed, unauthorized, unavailable, damaged, encrypted                         |
| Navigation         | first page, middle page, last page, direct page input, fit width, fit page, zoomed                        |
| Search and outline | closed, query with no result, one result, multiple results, no outline, nested outline                    |
| Selection          | toolbar, highlight palette, committed Ask context, note editor, copied, cancelled                         |
| Annotations        | empty, populated, selected, editing, deleting, permission denied                                          |
| Ask                | local new chat, streaming, response ready, suggestions delayed, historical, retried variants, source open |
| Conversations      | switcher closed/open, loading, empty, searched, pinned, active, local new chat                            |
| Responsive         | desktop, 320, 390, 430, soft keyboard, safe area, reduced motion                                          |
| Appearance         | Light, Dark, English, Simplified Chinese, long title, narrow content                                      |

Figma frame names and Storybook story names use the same state terms. Obsolete
Reader conversation-only mocks and any duplicated answer UI stay archived and
are not acceptance sources.

## Implementation boundary

Reader remains a vertical feature rather than a second application shell:

- `reader-page.tsx` owns route composition, URL state, query wiring, and the
  boundary between desktop panes and mobile sheets;
- `pdf-document-adapter.ts` owns the PDF.js contract, while `pdf-page.tsx` owns
  the Canvas, Text, Annotation, selection, and search-overlay surface;
- `reader-toolbar.tsx` owns the compact, non-modal PDF search experience;
- `reader-document-navigation.tsx` owns desktop Pages/Outline navigation and
  the shared outline tree used by the mobile document-navigation panel;
- `reader-context-panel.tsx` owns Ask, Annotations, Details, and the
  paper-conversation switcher;
- `features/conversation` owns the shared turn lifecycle, streaming response,
  worklog, sources, suggestions, answer actions, and composer used by both Home
  and Reader.

Reader-specific components may adapt document, page, selection, and annotation
context, but they must not fork the shared conversation reducer or final-answer
UI. Likewise, Home and Library must not import Reader internals.
