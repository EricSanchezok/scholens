# Reader experience

Reader is the document-focused surface for one accessible paper. It owns PDF
navigation, selection, annotation threads, private paper insights, document
details, and the contextual conversation entry point. A paper may be opened for
personal reading or inside one Project without creating another Document record.
Reader does not own a second conversation protocol or a second Workspace shell.

On a narrow mobile launch, the first successfully rendered PDF shows one quiet
AI reflow suggestion below the toolbar. It never starts MinerU, changes the
Reader URL, or replaces the PDF without an explicit user action. Dismissal is a
versioned device-local boolean. This suggestion takes priority over the
installable-Web-App promotion so Reader never stacks two onboarding actions at
the bottom of the phone viewport.

The active desktop acceptance source is Figma
[`50 — Reader`](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=390-2).
The canonical conversation boundary is
[`Reader conversation contract v3`](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=910-2).
Selection translation follows
[`51 — Translation`](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=720-965)
for hierarchy and states while code owns responsive containment and accessibility.
AI reflow and full translation extend the same document region according to
[ADR 0017](../../docs/decisions/0017-evidence-driven-reader-reflow.md).

## Product boundary

- The route is `/reader/[documentId]`; optional `project=<projectId>` identifies
  the active Project reading context.
- Library is the only paper collection. Opening a Library paper enters Reader;
  Reader does not create another paper record or another Library membership.
- Reader uses the shared conversation experience. `features/conversation` owns
  message rendering, ordered stream reduction, Worklog, final-answer actions,
  suggestions, Sources, and the Composer surfaces used by both Home and Reader.
  Reader contributes paper, page, selection, and annotation context through
  explicit adapter props. Reader translation is a separate content tool and
  never enters the shared conversation reducer.
- Opening a paper does not create a conversation. `New chat` enters a local
  blank state and the paper-scoped conversation is created by the first send.
- Selection translation is available in personal and Project reading contexts.
  It re-authorizes the paper independently of annotation audience and never
  creates a shared Conversation resource.
- AI reflow is an evidence-bound reconstruction derived from canonical parser
  Markdown and the original PDF. It is available in both contexts, never
  replaces the PDF, degrades uncertain blocks back to the original page, and
  keeps full translation private to the requesting user's preferences.

## Layout contract

Desktop Reader is an application viewport rather than a scrolling marketing
page. After the collapsed Workspace rail, Reader contains two independently
owned, top-aligned work regions:

1. the document region, whose toolbar combines Back to Library, the truncated
   paper identity, page controls, view controls, and document actions above the
   PDF thumbnail rail or the AI reflow outline and reading surface;
2. the contextual region, whose equally tall toolbar contains Ask,
   Annotations, Insights, Translate, Details, and Collapse above the active
   panel.

Reader must not add a full-width paper title row above these regions or a
separate Ask button outside the contextual panel. The panel width is responsive
between 23rem and 31.25rem so it remains secondary to the PDF without turning
conversation content into an unreadably narrow strip. Toolbars and panels may
be sticky inside their own regions, but the document shell must not make the
browser body scroll.

The Reader context selector is a 160 px desktop control that may shrink with
the toolbar but never wraps. It uses the shared compact toolbar Select rather
than a full-height form field. Its selected value is a single-line ellipsis and
its accessible name includes the complete current context. The personal label
is deliberately compact (`Personal` / `个人`); project options retain the real
title and may use two lines inside a bounded menu rather than widening the
toolbar.

The contextual panel disclosure occupies one stable far-right toolbar slot.
When the panel is closed that slot opens it; when the panel is open the same
screen edge closes it. Toggling the panel must not move the pointer target or
place the open action beside whichever document tool happens to be last.

Reader has four independently scrollable regions where applicable:

1. document navigation, showing PDF page thumbnails or the optional AI reflow
   outline;
2. the continuous PDF document canvas;
3. the active contextual panel;
4. the paper-conversation list disclosure.

Search is not a fifth panel. On desktop and mobile it temporarily replaces the
document toolbar controls with a compact query field, result position, and
previous/next controls. The PDF remains visible and interactive while search is
active. PDF view keeps its page-thumbnail rail and does not expose the PDF's
optional embedded bookmark tree. In AI reflow, the Outline control expands or
collapses a dedicated left navigation rail built from the semantic heading
blocks; it never opens a popover over the paper. The control occupies its stable
toolbar position immediately when AI reflow opens and remains disabled only
until the semantic headings are available, avoiding asynchronous layout shift.

At 320, 390, and 430 CSS pixels, Reader becomes an immersive document surface:

- the Workspace bottom navigation is absent;
- the top bar contains Back to Library, a truncated paper title, and document
  tools;
- the PDF remains visible as the primary surface;
- Ask, Annotations, Insights, Translate, and Details open as full-height bottom
  panels with safe-area padding;
- Search remains in the compact PDF toolbar. AI reflow exposes Outline as its
  own icon and opens the same semantic outline content in the shared responsive
  bottom-sheet pattern used by Sources;
- dismissing a panel preserves page, zoom, search result, draft, selection, and
  active conversation;
- the portalled panel follows the visual viewport height and vertical offset;
  the soft keyboard therefore resizes the active panel without hiding its
  switcher or Composer and without moving document controls underneath the
  keyboard.

Desktop columns must never be compressed into a narrow three-column layout.
The breakpoint changes the information architecture, not only widths.

## URL and local state

The URL is the shareable reading state:

- `page`: one-based current PDF page;
- `panel`: `ask`, `annotations`, `insights`, `translation`, `details`, or
  omitted;
- `conversation`: the active paper-scoped conversation ID, or omitted for the
  local blank state;
- `project`: an accessible Project that contains the Document, or omitted for
  personal reading.
- `view`: `reflow` for the responsive reading layout, or omitted for the
  canonical PDF default;
- `translate`: `full` to lazily translate visible reflow blocks, or omitted.

Zoom, fit mode, desktop AI reflow Outline disclosure, mobile AI reflow Outline
disclosure, search disclosure, search query, search match index, draft text,
active browser selection, pending turn context, annotation editor state, and
panel animation state are local. Invalid page, panel, and conversation
parameters are normalized after the document metadata is known and must not
produce a second history entry.

When `project` is present, Reader always refreshes the Document's accessible
Project memberships on mount. Cached membership data, an in-flight refresh, or
a failed refresh must not clear the Project context. Reader returns to personal
reading only after a new successful response confirms that the Project is no
longer accessible or no longer contains the Document.

## PDF surface

Reader uses the official `pdfjs-dist` Display and Viewer layers through the
feature-owned `PdfDocumentAdapter`. The worker and main package versions must
match. PDF code loads on the client and must not enter the server-rendering
bundle. The Web build publishes the locked package's WASM image codecs and
fallback modules under the release-scoped, same-origin
`/pdfjs/wasm/<release>/` path; `PdfDocumentAdapter` passes that directory as
PDF.js's `wasmUrl` and validates its manifest before opening a document.

Missing codec assets are a document-level terminal state with a download
action. Non-cancellation page render failures are shown on the affected page
with the same original-PDF download path; they must never remain as an
unbounded loading indicator or an empty page without feedback.

The document surface supports:

- continuous vertical page scrolling with lazy nearby-page rendering;
- viewport-driven current-page updates in the URL, while previous/next,
  thumbnails, internal PDF links, search results, and direct page input scroll
  the same document surface;
- programmatic navigation (page change, annotation focus, search cursor) scrolls
  only the PDF document container, never the Workspace Shell main scroller or
  the browser body;
- icon-only page controls retain their footprint at the first and last page,
  but express the unavailable direction with a muted icon and no filled block;
- lazy page thumbnails;
- zoom in/out, fit width, and fit page;
- PDF text search with result count and previous/next traversal;
- download URL refresh exactly once when a signed URL expires;
- Canvas, Text, and Annotation layers without mutating the source PDF.

Search hits, selections, and annotations are overlays derived from normalized
anchors. They are never burned into the PDF. A damaged, encrypted, unavailable,
processing, failed, or unauthorized document receives its own terminal state;
these states do not masquerade as an empty PDF.

Search highlights wrap only the matched characters rather than the containing
PDF.js text fragment. Matches that cross text-fragment boundaries remain one
logical result, and repeated matches inside one fragment remain separately
navigable. All results use the translucent document-search match role; the
current result uses the stronger current role and scrolls into view inside the
document container when the search cursor moves. Search styling never reuses
neutral selection or warning feedback colors.

## Reading activity and paper insights

The research-activity slice ships together with
[ADR 0039](../../docs/decisions/0039-first-party-research-activity-ledger.md);
these are runtime states, not speculative Figma-only analytics. Reader records
one private, owner-scoped session only while the account preference is enabled.
The shared tracker admits at most five seconds at a time, counts visible dwell
only while the document is foreground-visible and focused, and counts the
active estimate only while qualifying interaction is no more than 120 seconds
old. Normal delivery runs at most every 30 seconds, with an initial flush after
the first eligible evidence, exact-payload retry after a lost acknowledgement,
lifecycle flush when the document becomes hidden or leaves the page, and final
teardown when the Reader view changes or unmounts where the browser permits.
Moving between page targets does not itself force a network write. Retried
delivery remains cumulative and idempotent; the UI does not invent time after a
failed update.

PDF and AI reflow contribute to one Document timeline. PDF observation maps the
visible page rectangle to one of 20 normalized vertical regions. Reflow maps
visible blocks through their retained source spans to the same PDF page and
source-rectangle regions. Switching views therefore never starts a competing
heatmap or counts one interval twice. Selection text, pointer coordinates,
viewport captures, search queries, and document content are not activity
payloads. Optional Project context adds a removable Project attribution without
changing the personal owner of the session.

The private Insights panel has four ordered regions:

1. an all-time summary for active-reading estimate, visible time, sessions,
   active days, and substantive page coverage;
2. an ordered page-grid heatmap that can switch between an absolute duration
   scale and a within-this-paper relative scale;
3. an unsmoothed daily line trend, defaulting to the most recent 30 days;
4. a Top pages table with page, active estimate, session/revisit context, and
   coverage.

The primary duration label is always “Active reading estimate”; visible time is
supporting evidence and never silently replaces it. A page counts toward
substantive coverage only after 15 active-estimate seconds. The heatmap pairs a
single sequential intensity ramp with page number, numeric duration, a legend,
and distinct unvisited/no-data treatments. Each page cell is a real keyboard-
operable button whose accessible name includes page, estimated duration, and
coverage state. Activating it updates `page` and moves the document scroller to
that PDF source location, including when Insights was opened from reflow. Color,
relative intensity, and hover alone never carry the value.

The line chart keeps real zeroes, missing history, and the collection boundary
distinct and has a keyboard-accessible tabular equivalent. Neither the chart
nor heatmap claims gaze, attention, comprehension, or completion. An in-
progress local session may update its visible summary without changing the
settled server history until acknowledgement.
When only one calendar day has been collected, the trend region uses a compact
first-day state with one date and the measured values instead of drawing a
full-height line chart with duplicated endpoints.

`GET /api/v1/papers/{document_id}/insights` supplies the authorized projection.
Reader requests `range=all` for the summary and pages and `range=30d` for the
trend, then combines those two generated responses in the paper adapter; it
does not make one ambiguous range serve two visual meanings.
`reading_data_since`, `activity_history_complete_since`, and the metric-
definition version control the disclosure above the visualization. The first
anchors known evidence and trend densification; the second is the metric's
collection boundary. A finite window that starts before that boundary is
partial, while `all` means all history collected under this definition. A paper with
no post-launch activity receives an honest first-reading state rather than a
zero-filled historical year. When recording is off, existing private history
remains readable and the panel offers a direct Settings action for future
recording; it never describes retained history as deleted.
Finite trends retain response-time-zone calendar dates but aggregate whole
UTC-hour ledger buckets. When a local calendar boundary falls inside a UTC
hour, that incomplete first bucket is excluded rather than implying a
millisecond-exact period boundary.

The panel's Data control deletes this paper's reading history through
`DELETE /api/v1/papers/{document_id}/reading-activity` only after confirmation.
It names what is preserved: the paper, Library/Project membership,
annotations, conversations, outputs, and every other member's data. Reader
invalidates personal and Project insight queries after success. If the Reader
remains open, the tracker retires the deleted server session when its next
update receives the canonical not-found/ended response; later eligible reading
then starts a new session boundary. The UI does not claim to settle the tracker
before deletion, and deletion does not turn off future recording.

## AI reflow and full translation

The document toolbar exposes an explicit PDF/AI reflow switch. Reflow is a
continuous, single-column academic Markdown reading surface with a bounded,
tokenized measure — the article column caps at `layout.reading-column`, while
figure captions remain intentionally narrower within the Reader feature. The
shared measure is defined in `src/design-system/tokens/dimensions.json`; the
surface also provides semantic block types, overflow-contained tables and code,
authorized lazy image assets, Light and Dark support, and mobile safe-area
padding. Reflow uses the same shared academic Markdown renderer as conversation
messages, including its code-region preservation, MathML, and delimiter
normalization contract. Wide display equations
scroll horizontally inside their block, and tall equation glyphs are never
vertically clipped by that scroll container. Reflow does not preserve PDF page
whitespace or restart layout at page boundaries. Every block retains ordered
MinerU source spans and can return to the exact source page and rectangle.
Degraded blocks offer a compact PDF fallback and never display guessed
content.

Reflow headings form one semantic outline shared by both responsive
presentations. Desktop expands it as a left navigation rail beside the paper;
mobile opens it from the bottom with the shared Dialog handle, header, body,
safe-area, focus-trap, and dismissal behavior used by Sources. Selecting an
entry scrolls the reflow surface to its exact block and closes the mobile sheet.
The jump stays inside the reflow scroller (with the block's scroll-margin
clearance) and never scrolls the Workspace Shell main region. The toolbar never
substitutes an overflow-menu glyph for the Outline action.

Full translation is a toolbar action: a desktop popover and mobile bottom sheet
own language, bilingual/translation-only presentation, reference opt-in,
translation markers, and custom instructions. It is exposed only in AI reflow;
PDF view does not render an unavailable translation action. In reflow it observes semantic blocks in and near the viewport, streams at
most two translations concurrently, defaults to source followed by translation,
and retries one failed block without resetting the document. Disabling it aborts
in-flight browser work. The server's revisioned durable cache keys the repaired
display content while the browser still sends block identity, never source text.

Opening AI reflow does not implicitly schedule provider work. When no artifact
exists, the surface presents an explicit Start AI reflow action. A new or failed
attempt requires the user's enabled MinerU connection; active and completed
artifacts remain readable without another credential check. If the connection
is missing or invalid, Reader keeps the pending intent, explains why MinerU is
required, links to `https://mineru.net/apiManage/token`, and opens Settings →
Connections. Saving a new token resumes the intent once. Failed attempts retain
their safe failure class and expose Retry; retry creates an idempotent new
attempt without changing PDF availability.

## Selection and annotation threads

Selection has three deliberately separate lifetimes:

- `activeTextSelection` captures the normalized transient selection, renders
  its post-pointer overlay, and solely controls the floating toolbar;
- `pendingTurnContext` is the immutable selection snapshot committed to the Ask
  Composer;
- `annotationSelection` is the selection snapshot being edited as a new
  annotation thread.

The text-selection toolbar is absent until a real non-collapsed PDF text
selection exists. The fixed action bar is measured against the intersection of
the PDF viewport and the visual viewport; the translation preview and palette
are separate content below it and never participate in the anchor height. The
initial placement prefers below the selection and falls back above only when
the action bar cannot fit. That direction is locked for the selection's
lifetime, so streamed text growth cannot move the toolbar or flip the preview
to the other side. A new selection, zoom, resize, or visual-viewport size
change starts a fresh placement decision; scrolling and side-space changes only
recalculate the available clipping height while preserving the locked
direction. When the selection leaves the visible intersection the floating
surface is hidden, then restored when it returns, instead of searching for a
new page position. Horizontal placement remains clamped to the rendered page
and visual viewport. Its actions and color palette always sit on an isolated,
fully opaque elevated surface so document text cannot show through the
controls. It
contains only the semantic icons for Ask, Translate, Highlight, Add annotation,
and Copy;
Ask uses `AskIcon` (`ChatBubbleQuestion`) while Add annotation uses
`AddAnnotationIcon` (`Notes`), so their meanings cannot visually collide.
Accessible names live in tooltips and `aria-label`s rather than visible action
text. All five actions use the shared control-state and feedback rules.

While the pointer is down, the PDF text layer uses the dedicated translucent
blue document-selection token. The original Canvas text must remain legible
through the selection, matching the familiar line-by-line treatment of desktop
research readers rather than placing an opaque wash over the page. After
pointer-up, Reader replaces the browser-native selection with a normalized
overlay using the same token. The browser selection is cleared before this
overlay appears.

PDF selection is guarded by one document-owned adapter around the browser
Selection, its Ranges, and all PDF.js text layers:

- A selection sentinel (`.endOfContent`) plus a `.selecting` state mirror the
  PDF.js viewer behavior, so a drag that lands in the whitespace between
  lines or paragraphs never expands the browser selection to the whole text
  layer while the pointer is down.
- On pointer-up the commit waits one animation frame and a short settle window
  (100 ms). If the browser transiently collapses onto the sentinel, Reader
  retains the last complete selection snapshot from that gesture; a detached
  Range caused by a concurrent text-layer render is discarded instead of
  guessed. A live non-collapsed selection outside Reader always wins over that
  snapshot, so stale geometry can never revive and scroll back to an earlier
  page.
- A cross-page gesture remains one logical selection. Reader preserves the
  browser's exact quote and partitions geometry into ascending, unique page
  segments. The post-pointer overlay paints every segment, while the floating
  toolbar follows the browser focus end of the gesture. Viewport-driven page
  URL updates stay deferred until the post-pointer selection commit completes
  and never realign the PDF scroller in response to their own route update.
- The committed `selected_text` and overlay rectangles come from that same
  native Range. Partial words, search-highlight nesting, bidirectional text,
  and multi-column DOM order therefore keep the browser's own exact selection
  semantics instead of being reconstructed from whole text spans. Reader
  preserves PDF.js' complete
  TextLayer positioning contract so the selectable browser glyphs stay
  aligned with the Canvas glyphs; page-sized and out-of-page browser
  rectangles are rejected rather than clamped into false highlights.
  Overlapping PDF text fragments on the same visual line are coalesced, and
  the remaining geometry is painted once so translucent color can never
  accumulate into darker stripes. A committed PDF anchor contains at most 200
  rectangles in total. If coalesced browser geometry exceeds that bound,
  Reader samples it deterministically across pages and within each page,
  preserving the first page, last page, and native focus page rather than
  constructing a request the Server must reject; the exact selected text is
  unchanged.
- The overlay remains visible with the floating toolbar until the user acts,
  presses Escape, clicks elsewhere, or starts a replacement selection. Normal
  continuous scrolling and viewport-driven page changes preserve it.

- Ask copies the selection into `pendingTurnContext`, opens Ask, clears the
  browser selection, and adds a removable page chip; it never sends
  automatically.
- Translate opens the Translate panel and streams a translation for the exact
  normalized selection. When automatic selection translation is enabled, an
  unchanged selection waits 300 ms before starting. A replacement selection,
  page change, Escape, or component unmount aborts the stale request. Desktop
  shows a separate preview card below the fixed action bar. The card uses a
  fluid `clamp(22.5rem, 26vw, 30rem)` width, grows downward, and limits the
  preview body to `min(24rem, 40dvh)` before enabling contained internal
  scrolling. Preview growth never re-runs placement. The card is a scrollable
  summary with an independent button for the complete Translate panel; the
  panel remains the only guaranteed complete reading, copy, and annotation
  surface. At mobile widths the desktop preview is absent and the existing
  full-height panel opens instead. Streaming deltas are buffered and committed
  at most every 50 ms, while a stable status announcement reports only
  translating, completed, or failed states.
- Highlight first discloses the adjacent color palette, creates a thread with
  no comment, then clears the browser selection. In personal Reader its audience
  is personal. In Project Reader its audience defaults to personal but may be
  changed to the current Project before submission. The palette contains eight
  document-specific colors—yellow, red, green, blue, purple, magenta, orange,
  and gray—and never reuses feedback-state background colors. The persisted
  highlight appears immediately after the create response, remains visible
  without requiring the user to select it again, and may be recolored or
  deleted by its owner.
- Comment copies the selection into `annotationSelection`, opens the annotation
  editor, then clears the browser selection. The editor atomically creates one
  thread with its first comment and lets the creator choose the root color. In
  Project Reader its audience defaults to the current Project but may be changed
  to personal before submission. Subsequent replies have neither a color nor an
  audience control.
- Copy reports success through the shared copied state, remains keyboard
  accessible, and dismisses the toolbar after feedback.
- Clicking outside, Escape, or a replacement selection clears only
  `activeTextSelection`; committed Ask and annotation contexts remain.

Annotation rows and PDF overlays share a single active annotation ID. Choosing
either representation navigates to and emphasizes the other. Active state uses
a stronger fill only; it never draws a border or ring around every line of a
multi-line highlight. Exact-equal anchors are painted once, even when personal
and Project threads overlap; a count affordance discloses the individual
threads. A persisted PDF anchor uses one-based page numbers and zero-to-one
normalized rectangles. Legacy anchors project one page through `page_number`
and `rects`; multi-page anchors additionally carry ordered `segments`, with the
legacy fields equal to the first segment. Every action—Ask, Translate,
Highlight, Add annotation, and Copy—uses the same exact quote and logical
selection.
Agent-created quote-only annotations use a `parsed_text` anchor (canonical
offsets plus the immutable quote). After each PDF.js page render, Reader maps
that quote back to the text layer and paints the resulting normalized
rectangles with the same fill/underline rules as a user selection. An
unresolved parsed anchor is omitted rather than painted at a guessed location.
The empty Annotations panel is a quiet typographic prompt without a decorative
list icon; the panel tab already provides the necessary context.

One `AnnotationThread` is the only persisted annotation aggregate. Its immutable
audience is personal or the active Project; it owns the quote, typed position,
color, creator, status, and a chronological list of comments. A highlight is a
thread with no comments. Comments inherit the thread audience, never carry a
color, and are not nested.

Reader presents that aggregate as three modes without persisting another type:
a zero-comment thread is a Highlight, a commented personal thread is a Note,
and a commented Project thread is a Discussion. Only Discussions expose open,
resolve, and reopen language. Annotation collection responses carry the full
flat chronological timeline for every visible thread so the rail never relies
on disclosure state or a second detail request to show comments.

Personal Reader lists only the current user's personal threads. Project Reader
combines that user's personal threads with threads belonging to the current
Project. Its single compact filter menu offers audience (`All`, `Personal`, or
the current Project), mode (`Highlight`, `Note`, or `Discussion`), and current
versus resolved discussions. Audience badges use text rather than color. Open
annotations paint the PDF; resolved Project discussions are hidden by default
and use a subdued overlay only while the Resolved filter is active.

Commented anchors add one compact count marker at the PDF page edge; pure
highlights do not. Exact duplicate anchors paint once and aggregate their
comment count. Selecting a panel summary centers the first segment of the exact
anchor in the scroll viewport. Selecting a painted segment or its marker opens
the same thread in place without jumping away from the page the user is
reading. The panel's previous and next actions follow the current filtered
summary order across pages while keeping the PDF and panel selection in sync.

The annotation panel is one static, source-ordered list. Every card reduces its
source quote to a single ellipsized locator and always shows the complete flat
comment timeline; the source is already visible in the document pane, so
comments own the visual hierarchy. Hovering a card or moving keyboard focus
into it temporarily strengthens the exact PDF anchor without scrolling;
clicking locks the selection and centers the anchor without moving the card.
The rail is strictly vertical: neither long quotes, URLs, unbroken comment
content, nor bidirectional PDF text may widen it or introduce horizontal
scrolling. The one-line quote remains a locator rather than a second rendering
of the document.
The one-line reply field stays below its timeline and submits with Enter; it
has no redundant shortcut hint or visible send button. Resolve or reopen is a
compact thread action. Recolor and delete live in an opaque overflow menu;
recolor requires a click and then replaces that menu with a vertical palette,
never a hover-triggered submenu overlapping destructive actions. Per-comment
edit and delete remain in each comment's semantic overflow menu. Reply drafts
remain scoped to their thread and survive failed requests.
Comment authors use their shared profile avatar when available. The image is
decorative beside the visible author name, keeps the existing 28 px footprint,
and falls back to the localized author initial when absent or expired.
These thread and comment menus consume the shared collection-row and overflow
contract in [Component Development](./component-development.md); touch does not
depend on hover, while fine-pointer controls reveal on row hover or focus.

A comment-free Highlight paints a low-opacity color fill with no underline. A
Note or Discussion paints only a colored underline across its anchored text,
with no fill competing with the paper. Hover, keyboard focus, or selection may
strengthen the corresponding treatment, but persistent fill remains subtle and
no per-line boxes are drawn.

Project members may reply to open Project threads. The thread author may
recolor it; its author, the Project owner, and collaborators with Project edit
permission may resolve or reopen it. People edit and delete only their own
comments. A thread with another author's reply cannot be hard-deleted, and a
resolved thread must be reopened before receiving another reply. Personal
highlights and comment-free Project marks are deleted rather than resolved.

The Annotations query polls every ten seconds only while the panel is visible
and the document is focused. Outside that active poll it refreshes before the
earliest avatar URL expires, and checks missing avatars again within fifteen
minutes. The Server's bounded identity adapter cache reuses still-safe signed
views across those annotation polls and coalesces concurrent reads for the same
user. Window focus and every successful local mutation invalidate the query
immediately while retaining the previous list during the refetch. PDF.js
canvas/text rendering is isolated from hover, selection, and annotation-list
updates, so previewing a card or updating a comment does not clear and repaint
the document. The feature does not imply WebSocket delivery,
mentions, notifications, unread counts, reactions, or recursive replies.

## Contextual conversations

Reader in personal context lists only conversations whose scope is the current
paper. Reader in Project context lists the current user's private Project
conversations whose selected document context includes the open paper. Ask begins
with a compact, borderless current-conversation switcher and a separate New chat
action using the shared `NewConversationIcon` (`Edit`) from the Workspace
sidebar. The
search field and grouped Pinned/Recent list exist only while the switcher is
open; they are not a permanent row or horizontal pill strip. New chat remains a
local draft until the first send. Scope filtering and authorization happen on
the Server; the Web must not fetch global conversations and filter them
locally.

On phones, Reader preserves two distinct headers rather than compressing their
jobs into one row. The outer header retains Ask, Annotations, Translate,
Details, and the panel-close action. The inner Ask header runs from conversation
history, as its only flexible and widest item, to the compact label-only
reasoning-strength selector and New chat. Desktop retains the same outer panel
header and keeps reasoning in the Composer.

The open paper (and the active Project when reading inside one) is the default
research context of a new draft, not a locked boundary. The shared `@` context
trigger on the Ask Composer opens the same picker as Home, so the user may
narrow or broaden scope; edits persist like Home (create with `paper_context`,
then `PUT /api/v1/conversations/{id}/context` before the next turn).
The open paper and active Project seed their labels without fabricating a
Library response; all other discovery uses the shared server-backed context
catalog, so it is not capped by Reader's initial paper or Project page.
Turn-level selection and annotation contexts stay independent of that
conversation context. The Workspace sidebar conversation history remains
global and unfiltered on Reader: selecting a session there navigates to the
Home conversation workspace at `/?conversation=<id>`. Embedded Reader ask URLs
such as `/reader/<documentId>?panel=ask&conversation=<id>` are entered only
through the in-panel Conversation switcher and first-send creation, never
through the sidebar.

The Ask message viewport and Composer are two siblings inside the contextual
panel. Messages own the panel's vertical scroll, while the `context-panel`
Composer remains docked at the bottom. On desktop, context, input, the shared
reasoning trigger, and send controls share that surface; on phones, reasoning
moves to the inner Ask header. The Composer follows the
[shared shape and reasoning contract](./visual-language.md#shape-and-density)
for visual wrapping, height limits, and open-menu treatment. The switcher,
message viewport, and Composer are separated by spacing rather than stacked
card borders; the Composer uses the same `border-line` resting boundary and
desktop raised elevation as Home at the narrower panel measure. The transcript
and Composer share 20 px horizontal panel insets, so user messages align to the
Composer's right edge and assistant content aligns to its left edge. Its outer
surface alone owns keyboard focus. The Jump to latest action is anchored to the
message-viewport/Composer boundary so it remains fully above the Composer at
every expanded height.
An empty paper conversation uses a quiet title and supporting description with
no decorative icon or suggestion shortcuts; Home retains its existing empty
behavior through the optional structured-empty-state interface.
Side-panel presentation may change measure, spacing, and docking, but it must
reuse the same message, Worklog, answer, source, suggestion, retry, and variant
components as the workspace layout.

When a selected passage is sent, the turn context contains the document ID,
page number, selected text, and PDF anchor. A selected annotation is represented
by its `annotation_thread` ID. These contexts are persisted with the turn so a
historical message can restore its reading location. A new Project-context
conversation is Project-scoped and carries the open paper in its selected
document context; it remains private conversation history. Changing Project
clears an incompatible active Conversation while preserving the unsent draft.

The first send creates and activates the scoped Conversation as one operation.
Reader immediately keeps the new Conversation ID in the URL and renders the
user turn plus streaming response; a still-stale history query is never
interpreted as evidence that the Conversation belongs to another context. The
Conversation detail response is authoritative for scope validation, while the
history list refreshes independently. Expected creation is not announced by a
Toast because the active conversation and visible turn are already the
confirmation. Reader Toasts are limited to failed actions, lost access, or an
invalid deep link, and must explain the resulting user-visible recovery.

The shared conversation contract remains unchanged:

- ordered streaming and Worklog during execution;
- `response_ready` as the persisted answer boundary;
- optional turn suggestions in the same stream;
- identical all-message Copy/Edit, durable branch selection, retry, completed
  variant, elapsed-duration, source, and suggestion behavior;
- a failed or cancelled active leaf that remains visible and retryable after
  refresh without exposing raw server exceptions;
- a single responsive Sources panel.

Current-paper sources navigate inside the open document. Other paper sources
open that paper's Reader route. External sources open a new browser tab.

## Details

Details presents only canonical document data: title, authors, abstract, DOI,
journal or venue, publication date, file information, parsing status, and
quality. Missing values use explicit unknown or unavailable copy rather than
invented metadata. Project membership and collaborative sharing remain
unavailable until their owning features exist. Translation preferences and
results belong to the Translate panel rather than document metadata.

## Acceptance matrix

Every reusable Reader component needs Storybook coverage and the route needs
Playwright coverage for the following matrix:

| Surface            | Required states                                                                                                                                                                           |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Document           | loading, ready, processing, failed, unauthorized, unavailable, damaged, encrypted                                                                                                         |
| Navigation         | first page, middle page, last page, direct page input, fit width, fit page, zoomed                                                                                                        |
| Search and outline | closed, query with no result, one result, multiple results, desktop reflow rail, mobile reflow sheet                                                                                      |
| Insights           | recording on/off, first reading, all-time summary, absolute/relative heatmap, 30-day trend, top pages, partial history, expired fine detail, keyboard page jump                           |
| Selection          | toolbar, highlight palette, committed Ask context, translation preview, note editor, copied, cancelled                                                                                    |
| Translation        | idle, ready, streaming, cached, quota exhausted, retryable error, custom preferences                                                                                                      |
| AI reflow          | pending, original, translated, streaming block, failed block, job failure, retry, PDF return link                                                                                         |
| Annotations        | empty, populated, selected, editing, deleting, permission denied                                                                                                                          |
| Ask                | local new chat, streaming, response ready, suggestions delayed, historical, prompt edit retained on early failure, branch pager, failed leaf after refresh, retried variants, source open |
| Composer           | compact full pill, visual wrap or explicit newline, fixed 24 px expanded corners, maximum-height internal scroll, desktop reasoning closed/open                                           |
| Conversations      | switcher closed/open, loading, empty, searched, pinned, active, local new chat, mobile dual headers and ordered inner controls                                                            |
| Responsive         | desktop, 320, 390, 430, soft keyboard, safe area, reduced motion                                                                                                                          |
| Appearance         | Light, Dark, English, Simplified Chinese, long title, narrow content                                                                                                                      |

### Figma and Storybook acceptance mapping

The active Figma Reader page above remains the visual-intent source. The
collaboration contract is executable in Storybook, plus route Playwright where
the full Reader composition is required. Until dedicated collaboration frames
receive stable node IDs, reviewers use the named `50 — Reader` states rather
than inventing links:

| Figma `50 — Reader` state     | Executable acceptance evidence                            |
| ----------------------------- | --------------------------------------------------------- |
| Personal highlight            | `CommentlessPersonalHighlight`                            |
| Project discussion            | `ProjectDiscussionTwoAuthors`                             |
| Resolved Project discussion   | `ResolvedProjectDiscussion`                               |
| Project audience before save  | `ProjectAudience`                                         |
| Project context selector      | `ProjectContext`, `LongProjectContext`                    |
| Light/Dark annotation palette | `AnnotationThread`, `AnnotationPaletteDark`               |
| Narrow annotation composer    | `NarrowSelection`                                         |
| Selection translation states  | `Ready`, `Streaming`, `CompletedAndCached`                |
| Mobile translation            | `NarrowMobile`                                            |
| Dark translation              | `CompletedDark`                                           |
| AI reflow semantic structure  | `AcademicStructure`, `DegradedEvidence`                   |
| AI reflow outline             | `DesktopSidebar`, `Narrow`, `Dark`                        |
| AI reflow translation modes   | `Bilingual`, `TranslationOnly`, `Streaming`               |
| AI reflow translation error   | `TranslationError`, `PartialFailure`                      |
| AI reflow toolbar settings    | `DesktopPopover`                                          |
| AI reflow mobile/Dark         | `SmallMobile`, `LargeMobile`, `MobileBottomSheet`, `Dark` |
| Shared mobile Ask Composer    | `ContextPanelMobileVisualWrapExpansion`                   |
| Mobile Ask dual headers       | Reader Playwright `keeps Reader Ask controls…`            |

The Project discussion stories deliberately show flat replies from two
authors, immutable audience badges, root-only color, and resolve/reopen
capabilities. The route E2E owns URL restoration, invalid-context fallback,
atomic first-comment creation, exact-anchor de-duplication, and project-scoped
Ask filtering.

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
- `reader-document-navigation.tsx` owns the desktop PDF thumbnail rail;
- `reader-context-panel.tsx` owns contextual navigation and composes Ask,
  Annotations, Insights, Translate, Details, and the paper-conversation
  switcher;
- the shared research-activity feature owns preference, session, cumulative
  tracker, insight-query, completeness, and estimate-formatting contracts;
  Reader adapts PDF and reflow visibility into that feature and owns the
  paper-specific heatmap, trend, Top pages table, and page navigation;
- `translation/` owns translation preferences, the standard SSE adapter, the
  selection lifecycle controller, and translation panel states;
- `reflow/` owns the typed artifact query, semantic Outline shared by the
  desktop rail and mobile bottom sheet, block-only SSE adapter, bounded
  visible-block scheduler, and responsive reflow presentation;
- `features/conversation` owns the shared turn lifecycle, streaming response,
  worklog, sources, suggestions, answer actions, and composer used by both Home
  and Reader.

Reader-specific components may adapt document, page, selection, and annotation
context, but they must not fork the shared conversation reducer or final-answer
UI. Likewise, Home and Library must not import Reader internals.

## Motion acceptance

Reader motion is contained around the document. The context panel and desktop
AI reflow outline disclose directionally, and the active Ask/Annotations/
Translate/Details content performs a bounded replacement. The selection
toolbar, translation preview, and palette share one positioned surface and do
not animate independently across the PDF. PDF pages, continuous document
scroll, zoom, search traversal, text selection, and streamed translations are
not decorative motion targets. Smooth programmatic outline navigation becomes
direct in Reduced mode; spatial panel/layout animation and perpetual loading
also stop while page, selection, draft, annotation, and URL state remain intact.
