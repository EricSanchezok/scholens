# Home Experience

Home is the first production slice of the replacement frontend. Its canonical
design is the Figma page `20 — Home`, including the default workspace, collapsed
sidebar, context picker, recent content, and conversation states. Figma owns
visual hierarchy and acceptance; this document records runtime ownership and
the deliberately deferred boundaries.

## Entry and ownership

- `/` requires an authenticated session. Anonymous visitors are sent to
  `/login` with a safe return target.
- The selected conversation is shareable navigation state and therefore lives
  in `?conversation=<uuid>`. A refresh restores that conversation.
- Conversations, papers, projects, and message history are server state owned
  by TanStack Query. Composer input uses React Hook Form and Zod; its form state
  is owned by `HomeWorkspace` so responsive composition changes never discard
  an unsent draft. Sidebar and picker state remain local. An in-progress
  subscriber is local, but accepted generation and its terminal state are
  Server-owned and survive route changes, backgrounding, reload, and offline
  intervals.
- Desktop and mobile share one navigation model, actor state, conversation
  state, and `AppShell` boundary, but use device-appropriate compositions. The
  desktop sidebar is 288 px when expanded, 320 px on ultrawide viewports, and
  64 px when collapsed. Phones use
  a persistent bottom bar for Ask, Library, Projects, and Me. Their full-screen,
  opaque navigation hub is reserved for an identity link to Me, unified search,
  and complete conversation history; it enters from the leading left edge to
  preserve continuity with the hamburger trigger and desktop rail, and it does
  not render the desktop Sidebar inside a narrow drawer. The hub closes with a
  directional return control rather than a dismiss-style X. Search and New
  conversation remain anchored in one bottom utility row above the safe area;
  the conditional Install entry sits immediately above it. The desktop account
  dropdown is never embedded in this mobile hub.
  The persistent destination row is integrated into the canvas: it has no
  enclosing pill, structural border, or elevation shadow. Only the current
  destination receives the existing filled circular icon state and stronger
  label, so selection remains explicit without making navigation float above
  the page.
- `AppShell` is fixed to the visual viewport and prevents document scrolling.
  On phones it continuously sizes itself from `visualViewport` (height and
  offsetTop) so expanding mobile browser chrome after a client-side tab switch
  cannot clip the bottom Dock; keyboard focus still overrides that measurement
  with the focused soft-keyboard viewport. Its `main` element is the sole
  vertical conversation scroller and clips horizontal overflow; the desktop
  Sidebar and mobile Dock remain outside that scroll ownership. Message content
  keeps only the padding needed for its in-flow Composer, so scrolling to the
  latest turn cannot expose an artificial blank page below the answer.
- The desktop conversation lane has one 832 px maximum measure shared by the
  transcript and Composer. User messages align to its right edge; assistant
  messages and Worklogs align to its left edge, and the rendered assistant
  content occupies that full lane instead of introducing a second prose-only
  maximum. The Reader side-panel adapter keeps the same relationship with 20 px
  horizontal insets rather than adding a second, narrower message measure.
- Collapsing the desktop sidebar changes only its horizontal geometry. The top
  control, navigation rows, and account trigger retain their vertical anchors.
  The expanded rail renders the shared Scholens raven lockup; the collapsed
  rail keeps its controls semantically explicit rather than turning the brand
  mark into a functional glyph.
  Unified workspace search is a compact header action beside the collapse
  control in the expanded rail; the collapsed rail places the same action below
  New chat so it remains reachable without relying on `Command/Ctrl+K`. Every
  desktop and mobile launcher opens the same dialog, initially focused on the
  Conversation tab; switching to Papers preserves the current keyword.
- Desktop sidebar density remains subordinate to the reading surface: primary
  navigation uses 40 px rows with 20 px semantic glyphs in 24 px fixed slots,
  conversation history uses 48 px two-line rows so title, research context,
  relative update time, and contextual actions can be scanned independently,
  and the account trigger uses a 48 px row. Expanded
  sidebar navigation, conversation titles, and the actor name share the 13 px
  `type.sidebar` role; the product label retains the 14 px UI role and the email
  retains the 11 px caption role. The account trigger preserves its full hit
  target while using a compact avatar and horizontal inset so a normal full
  email has width headroom across browser font metrics rather than merely
  fitting one reference screenshot.
- The desktop sidebar is one continuous canvas rail separated from content by
  one quiet boundary. Navigation, history, and account controls do not become
  independent cards; only the current or hovered row receives a rounded local
  surface. This keeps the shell visually continuous with Library and Projects.
- Every conversation row exposes Open in new tab plus capability-gated Rename,
  Pin/Unpin, and Delete actions through the shared overflow contract. Desktop
  rename stays inline; mobile rename uses a safe-area-aware bottom dialog.
  Rename and pin optimistically update every conversation-list cache and roll
  back on failure. Delete waits for Server success before removing the row; if
  it deletes the active conversation, only the `conversation` URL parameter is
  removed so the Reader document, Project, panel, and other navigation state
  remain intact.
- `WorkspaceShell` owns a workspace-wide infinite conversation query. It shows
  every pinned conversation, then non-pinned history grouped as Today,
  Yesterday, Previous 7 days, Previous 30 days, and month. The history region
  scrolls independently between fixed navigation and account regions and
  continues loading with an intersection sentinel plus a keyboard-operable
  fallback. If a URL opens an old conversation that is not loaded yet, a
  temporary Current conversation group keeps it visible; normal pagination
  removes that duplicate once the canonical row arrives. Reader and Project
  context panels retain their own narrower conversation queries.
- The phone navigation hub fills the viewport and owns an opaque sidebar
  surface above a lower stacking-level backdrop. Its history is independently
  scrollable between fixed account and utility regions. Visible controls retain
  at least 48 px touch targets even though typography and glyphs follow the
  compact sidebar hierarchy.
- The phone utility search control is a launcher, not an in-memory title
  filter. The unified search dialog is full-screen on phones and uses the same
  Server queries, tabs, result semantics, loading/error/empty states, and
  keyboard behavior as desktop.
- Deferred destinations retain their product names in the visible navigation;
  availability is disclosed through the disabled control and its tooltip, not
  implementation-plan copy.

## Data and streaming

Home consumes only the public conversation, project, library-paper, and actor
contracts. It does not import from `client/` and does not define duplicate wire
DTOs.

Conversation continuation uses the direct durable SSE response, and a first
prompt uses `POST /api/v1/conversations/{id}/start` to atomically create the
client-identified Conversation, Turn, Response, job, and outbox dispatch. HTTP
acceptance therefore makes generation durable and enables Stop without a
separately committed empty Conversation or a second subscription round trip.
The optimistic transcript and Composer clear happen immediately on local
submission and are rolled back exactly if acceptance fails. Explicit
`Prefer: respond-async` remains the compatible detachable `202` mode for other
clients. If the direct subscription drops, the Web app follows the response
event endpoint with `Last-Event-ID`; both paths use one standard SSE decoder.
The stream accepts `start`, the stable-ID
`assistant_item_start → delta → complete`
lifecycle, `activity`, `references`, `response_ready`, `suggestions`,
`complete`, `cancelled`, and `error`. The Server buffers model text until the
complete node establishes its role. Text accompanying a runtime tool call may
arrive as bounded `progress`. Direct requests opt into candidates, and the
additive `/events/candidates` resume subscription returns sanitized partial
`final_answer` arguments through
`assistant_candidate_start`, `assistant_candidate_delta`, and
`assistant_candidate_reset` while the structured answer is still arriving. A
bounded suffix and all private citation markers stay server-side, and a model
validation retry resets the candidate before replacement text appears. Clients
do not fall back to the original `/events` route: an incompatible deployment is
surfaced and retried instead of silently changing an active answer's event
contract. A `final` item completes only after structured answer validation.
`response_ready` supplies the complete persisted turn
snapshot, and an optional `suggestions` event may supplement it before
`complete` closes the stream. The client never infers phase from prose. A
sanitized answer candidate renders only in the main answer lane while it is
streaming; it is replaced by the canonical validated item on completion and is
cleared before a validation retry. Candidate text never becomes a Worklog row,
enables answer actions, or enters persistence. Progress and activity share one
sequence and become an ordered worklog. The final answer remains outside that
trace and is always visible.

`activity` is an ID-addressed, sanitized tool lifecycle record without a raw
tool name. Adjacent tool entries with the same outcome are rendered as one
category-count batch; outcome changes and progress text separate batches. Model
reasoning, provider heartbeats, raw tool names, arguments, and return payloads
are not product UI. Only final items may
publish references. `response_ready` releases the Composer and completed-answer
actions without waiting for a GET refetch, conversation title, or suggestion
sidecar. `complete`, `cancelled`, and `error` are terminal. A dropped
subscription reconnects with bounded backoff and event-ID deduplication; it
never creates a second Turn or retries model generation. Unmounting or changing
routes aborts only the local subscription. Moving to another conversation also
releases that conversation's local Composer state; its accepted generation
continues on the Server, so a different conversation can generate independently
while the original remains limited to one running response. Stop is a separate
authorized Server cancellation and the UI discloses when that cancellation
cannot yet be confirmed. The submitted user message enters the optimistic
transcript and the Composer clears immediately. Before HTTP acceptance the
pending state does not expose an invalid Stop action; after acceptance the
standard stop-square action remains for the lifetime of the durable generation.
A pre-acceptance failure restores the exact draft and focus; a later stream
failure preserves the submitted user message in the transcript instead of
restoring duplicate text to the Composer.
Capacity dependency outages are returned as `unavailable`, not as a user quota
exhaustion. The interface preserves the failed user message, explains that it
was saved, and retains stable failure code, retryability, correlation ID, and
public diagnostic ID across refresh without exposing provider bodies, raw
exceptions, or Redis details. Provider timeouts, invalid output, filtering,
operation limits, and configuration failures have distinct localized copy.

Incoming events update one feature-private target state, while React can read
only a separately published snapshot. Consecutive answer deltas are coalesced
and published at most every 50 ms, aligned to an animation frame while visible;
terminal, cancellation, error, and reset events publish immediately. Historical
turns, Workspace navigation, and Reader pages do not subscribe to live content,
and streaming Markdown consumes a deferred snapshot. Conversation auto-follow
observes real transcript size changes and
drives one retargetable animation toward the latest content; it never starts a
new native smooth-scroll operation for each token. Wheel, touch, keyboard, or
scrollbar movement away from the bottom cancels following immediately and
reveals Jump to latest. Returning near the bottom or activating that control
re-engages following. Reduced-motion users move to the current target without
animation.

Every writable user message exposes Edit followed by Copy; when alternate
prompt branches exist, their pager follows those actions in the same row.
Editing saves a durable
sibling prompt branch at the original depth, selects that branch, and generates
its first response from the shared prefix. The selected branch replaces the
entire visible suffix rather than splicing turns client-side. Save remains in
the editor until the durable POST is accepted; an early HTTP,
network, abort, or malformed-stream failure keeps the exact draft, error state,
and editor focus for correction or retry. Once accepted, the editor closes and
the standard live-turn recovery contract takes over. A branch pager beside the
user message selects adjacent sibling branches and persists that selection so
refresh restores the same path. On fine-pointer desktop, Edit and Copy appear
on message hover or keyboard focus-within; touch layouts keep them visible.
The editor reuses the Composer's quiet rounded surface and surface-level focus
treatment instead of nesting a native textarea frame inside the message.

Enter submits from the workspace and context-panel Composers only when no IME
composition is active. The Enter key that confirms a Chinese, Japanese, Korean,
or other composed candidate updates the draft without sending it; the user's
next explicit Enter submits. The same guard applies to message-edit shortcuts
and Reader text controls that bind Enter to an action.

At `response_ready`, the turn snapshot is upserted directly into the TanStack
Query cache; only conversation detail and list are invalidated in the background
to synchronize a possible first-turn title. A turn owns the submitted prompt,
its generated response variants, and exactly three optional follow-up
suggestions. Only the latest turn may expose retry, variant selection, and
suggestions; once a newer submission starts, those prior controls disappear in
the same render while copy and sources remain available for completed answers.
Every completed answer exposes a copy action for the selected final response.
It uses the shared transient-action contract: the control keeps its position
and focus, changes to a success or error glyph with a short anchored label,
announces the outcome politely, and returns to its idle state without shifting
the action row. Clipboard failure is never silent.
Retry creates a new response variant under the same active leaf turn, selects
it at `response_ready`, reuses the turn suggestions, and never duplicates the
user prompt. A failed or cancelled active-leaf response remains serialized as
safe status plus duration, without raw exception text, and is retryable at the
same leaf after refresh. Version navigation includes completed variants only
and is shown only while that turn remains latest.
Selecting a suggestion only fills and focuses the Composer so the user can edit
it before sending. Suggestion generation is a non-critical sidecar that starts
only after the main provider produces its first public stream event. If it
finishes later, its typed SSE event updates
both live state and the latest cached turn. There is no pending card, failure
message, polling state, or automatic client retry; a failed or timed-out sidecar
simply leaves suggestions absent without delaying answer actions.
Grounded answers expose one source-count pill in the same action row. Selecting
that pill opens the single canonical source panel: a bottom sheet on phones and
a centered dialog on desktop. Inline citation markers open that same panel and
highlight the corresponding source instead of introducing a second source
list. Document and external sources share the same evidence rows; only external
sources navigate away, and they open in a new tab.
Conversation content uses the shared academic Markdown renderer also consumed
by Reader reflow. It supports inline `$...$` and `\\(...\\)` plus display
`$$...$$` and `\\[...\\]`, leaves inline and fenced code literal, and retains
KaTeX MathML for assistive technology. Wide display equations scroll within
their own focusable block instead of widening the message lane or clipping tall
glyphs. Citation annotations are inserted against the original answer offsets
before math delimiters are normalized, so formula rendering cannot move a
source marker onto the wrong passage.
The Server replaces the default Sidebar title once after the first successful
assistant reply. Follow-up turns do not regenerate it, and user renames are
never overwritten by title generation. If optional model title generation
fails or times out, the Server derives a cleaned title of at most 60 characters
from the first user question. The administrator-only, idempotent maintenance
command applies the same fallback to legacy default-titled conversations.

## State coverage

| Surface      | Deterministic coverage                                                                                                                                                  |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Home data    | populated, loading/slow, empty, and recoverable error                                                                                                                   |
| Navigation   | 288 px desktop, 320 px ultrawide, collapsed, full paginated history, old active conversation, mobile full-screen hub, unified search, active conversation               |
| Context      | entire library and selected project/paper sources, including search                                                                                                     |
| Conversation | direct answer, tool activity, timed result, prompt edit/branch, partial failure, reconnecting, stop failure, refresh-safe retry, references, complete, cancelled, error |
| Presentation | English, Simplified Chinese, Light, Dark, 1440 px, 390 px, and 320 px overflow check                                                                                    |

The Figma conversation-state frames and Storybook stories map one-to-one:

| Figma `20 — Home` state   | Storybook acceptance state                           |
| ------------------------- | ---------------------------------------------------- |
| Provisional response      | `Conversation View / Provisional Response`           |
| Progress before tools     | `Conversation View / Progress Before Tools`          |
| Consecutive tool batch    | `Conversation View / Consecutive Tool Batch`         |
| Strategy change           | `Conversation View / Strategy Change`                |
| Completed collapsed       | `Conversation View / Completed Collapsed`            |
| Completed expanded        | `Conversation View / Multiple Tools Expanded`        |
| Partial failure           | `Conversation View / Partial Failure`                |
| Cancelled                 | `Conversation View / Cancelled`                      |
| Direct answer             | `Conversation View / Direct Answer`                  |
| Timed direct answer       | `Conversation View / Timed Direct Answer`            |
| Error                     | `Conversation View / Error`                          |
| Failed leaf after refresh | `Conversation View / Failed Leaf After Refresh`      |
| Mobile reconnecting       | `Conversation View / Mobile Reconnecting`            |
| Mobile reconnecting dark  | `Conversation View / Mobile Reconnecting Dark`       |
| Stop not confirmed        | `Conversation View / Stop Could Not Be Confirmed`    |
| Latest answer actions     | `Conversation View / Latest Answer Actions`          |
| Retried variants          | `Conversation View / Retried Response Versions`      |
| Prompt branch pager       | `Conversation View / Prompt Branch Pager`            |
| Historical answer         | `Conversation View / Historical Answer Has No Retry` |
| Suggested follow-ups      | `Conversation View / Suggested Follow Ups`           |
| Answer sources            | `Conversation View / Answer Sources`                 |
| Math with answer sources  | `Conversation View / Math And Sources`               |

The canonical ordered-harness matrix is Figma node `893:3415`,
`Matrix / Ordered conversation harness v3`, with Desktop Light/Dark and Mobile
Light/Dark groups. The superseded per-tool activity
checklist is archived under `99 — Archive / Interaction States`.

The final-answer action and evidence contract is the authoritative Figma matrix
[`906:2628`](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=906-2628),
`Matrix / Conversation actions, branches and sources v3`:

| Figma `20 — Home / Final answer actions and sources` | Storybook acceptance state                              |
| ---------------------------------------------------- | ------------------------------------------------------- |
| Latest answer actions                                | `Conversation View / Latest Answer Actions`             |
| Retried response versions                            | `Conversation View / Retried Response Versions`         |
| Historical answer                                    | `Conversation View / Historical Answer Has No Retry`    |
| Suggested follow-ups                                 | `Conversation View / Suggested Follow Ups`              |
| Mobile answer rhythm                                 | `Conversation View / Mobile Answer Rhythm`              |
| Streaming                                            | `Conversation View / Provisional Response`              |
| Response ready, suggestions ready                    | `Conversation View / Response Ready With Suggestions`   |
| Response ready, suggestions arrive later             | `Conversation View / Response Ready Before Suggestions` |
| Retry in progress                                    | `Conversation View / Retry In Progress`                 |
| Retry failed                                         | `Conversation View / Retry Failed`                      |
| Source count and evidence panel                      | `Conversation View / Answer Sources`                    |

The matrix's response-finalization lifecycle is recorded at node `961:2605`.
It covers Streaming, response-ready with immediate or later suggestions,
Historical answer, and Retried variants, together with mobile
Light/Dark final actions, the mobile source bottom sheet, the desktop action row
and centered source dialog, an inline selected
citation, three editable follow-up suggestions, and pointer/touch versus
keyboard focus acceptance. Storybook keeps locale, appearance, and 320/390/430
px viewport controls available for the same executable states. The superseded
phone reading surface at node `898:2628` is archived under
`99 — Archive / Interaction States`; it is historical reference, not a current
implementation contract.

Each Worklog summary ends with an elapsed duration. While generation is active
the visual value updates without turning every tick into a live-region
announcement; the settled value is announced once. Durations under one minute
use seconds and longer work uses minutes plus seconds. The disclosure chevron
sits immediately after the summary text instead of occupying the row's far
edge, so the control reads as one compact phrase.

The answer-action row uses one Iconoir source with optical sizing rather than
equal glyph sizes: Copy renders at 20 px and Refresh at 16 px so their visible
bounds match. Version navigation, Copy, and Refresh form one gapless tool group
with transparent resting surfaces; hover, active, and keyboard focus reveal
the individual hit target without dividing the row into persistent blocks.
Mobile hit targets remain 44 px and desktop hit targets are 32 px. Disabled
arrows retain normal opacity and use the muted semantic color. Follow-up
suggestions have no visible heading or repeated icon: phones use 44 px pills.
On desktop, actions and suggestions share one response footer. Suggestion rows
use secondary text, subtle separators only between rows, and a local rounded
hover/focus surface; there is no outer divider or permanent card background.
Each label stays on the response text baseline while its 12 px internal hit
inset is preserved by extending the row surface beyond the footer edge. This
preserves an actionable next-step identity without competing with the answer
or relying on repeated glyphs.
On phones, the final answer, its 44 px action row, and its suggestions form one
proximity group: the answer-to-actions and actions-to-suggestions boundaries
each use a single 8 px gap. Components must not add a second top padding at
either boundary. Touch targets keep their full size even though the visible
glyphs and surfaces read as a compact continuation of the answer.

Reader consumes the same message contract instead of defining a second
conversation renderer. Its authoritative Figma matrix is
[`50 — Reader / Matrix / Reader conversation contract v3`](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=910-2):
Reader contributes only the current paper, passage, and selection as default
scope; the ordered worklog, final-answer actions, suggestions, citations, and
source panel remain the Home semantics described above. The former Reader
process-card frames are archived under `99 — Archive / Interaction States` and
are not implementation references.

The mobile Dock acceptance inventory extends that mapping:

| Figma `20 — Home / Mobile` target | Storybook acceptance state                          |
| --------------------------------- | --------------------------------------------------- |
| Empty + Dock / Ask selected       | `Workspace / Mobile Empty`                          |
| Recent research launcher          | `Workspace / Mobile`                                |
| Launcher loading                  | `Dashboard / Mobile Recents Loading`                |
| Launcher error                    | `Dashboard / Mobile Recents Error`                  |
| Launcher long titles at 320 px    | `Dashboard / Mobile Recents Long Titles`            |
| Launcher removed after submit     | `Workspace / Mobile Recents Disappear After Submit` |
| Conversation + Dock               | `Workspace / Mobile Conversation`                   |
| Keyboard Open                     | `Workspace / Mobile Keyboard Open`                  |
| Library scope                     | `Research Composer / Library Scope`                 |
| Multiple-paper scope              | `Research Composer / Multiple Papers Scope`         |
| Long project scope at 320 px      | `Research Composer / Long Project Scope`            |
| Multiline input                   | `Research Composer / Multiline Input`               |
| Mobile reasoning menu             | `Workspace / Mobile Reasoning Menu Open`            |
| Mobile navigation panel           | `Workspace / Mobile Navigation Open`                |
| Desktop reasoning menu            | `Research Composer / Desktop Reasoning Menu Open`   |
| Streaming / Stop                  | `Research Composer / Streaming Stop`                |
| 430 px Dark English               | `Research Composer / Dark English Large`            |

The mobile acceptance set is synchronized to the active `20 — Home` Figma
page. Its primary navigation state uses the shared action surface and inverse
icon roles for the current destination, while inactive destinations retain the
muted semantic role. Each future destination must supply its own
`aria-current="page"` state when its vertical slice becomes available; Home
does not create placeholder routes merely to demonstrate those states.
The selected-state specimens are the node-specific
[Ask](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=882-3416),
[Library](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=882-3437),
and
[Projects](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=882-3458)
frames. Library and Projects document the future selected visual state only;
their runtime destinations remain deliberately unavailable in the Home slice.

The former heavy process card and per-tool checklist are archived in Figma and
are not supported Web states. `Conversation View / Narrow Long Subject` and
`Conversation View / Simplified Chinese Dark` supplement the Figma mapping with
runtime overflow, locale, and appearance coverage. Optimistic and persisted
turns are reconciled by `turn_id`; the isolated deduplication state guards
against showing the same submitted prompt twice while a stream is active.

Each generated response owns one `ConversationWorklog` before its final answer.
During a run it opens by default; a final item collapses it unless the user has
manually chosen a state. Persisted history starts collapsed. Expanded rows
interleave concise progress with outcome-homogeneous tool batches, show at most
two safe subject examples per batch, and never create nested tool disclosures.
Each batch names its visible state, and the summary labels the reference count
as cited sources rather than retrieval results. The summary is the only polite
live-region announcement, so screen readers do not
receive every tool update. The same semantic component is used on desktop and
mobile, with compact responsive spacing and no inner scrolling surface.

On phones, the shell uses a 64 px content bar plus platform safe-area insets.
The bar owns navigation, a compact text-only reasoning-strength selector, and
the new-chat action. Its trigger and narrow menu expose only the Standard and
Deep labels; descriptions remain a desktop Composer affordance. Model
selection is not part of the Scholens product surface. Conversation content uses a stable
16 px body with 28 px line height, 22/19/17 px heading steps, and 20 px
horizontal gutters at the primary phone widths (16 px at 320 px). Browser text
adjustment is fixed at 100%, preventing Android Chrome from inflating a long
answer independently of the rest of the shell. CJK falls back to the platform
system family; emphasis uses weight rather than another font face. Long words
and links wrap inside the reading measure, while only code blocks and tables
receive their own horizontal scrolling surface.

The mobile worklog keeps the same typed ordered entries as desktop, but its
expanded state uses a quiet vertical rail and one semantic marker per progress
phase or grouped tool batch. It does not restore individual tool cards or
per-call checkmarks. References are summarized as one touch-sized source pill;
the source rows appear only when that disclosure is opened. When the reader
moves away from the bottom of an overflowing conversation, a 48 px
`Jump to latest` action appears immediately above the Dock and disappears on
return. These are presentation rules only: desktop density, Agent events, and
persisted conversation data remain unchanged. A single
`MobileBottomDock` owns the Composer, primary navigation, horizontal safe-area
gutters, bottom safe area with a minimum pad fallback
(`max(0.5rem, env(safe-area-inset-bottom))`), and stacking layer. The Composer and navigation are
separated by 4 px inside the Dock rather than behaving as independent floating
surfaces. The Composer retains its deliberate elevation; the navigation row is
flat on the Dock canvas, and the non-layout 20 px fade is rendered only when a
Composer needs a transition from scrolling content.
Only one real Composer is mounted at a time. On desktop it rests as a rounded
single-line bar and expands to a rounded panel only when the written prompt
becomes multiline or long. Explicit project and paper selections never add a
second row: the AtSign trigger carries a compact count badge, caps its visible
value at `9+`, and opens the existing context picker for inspection or removal.
Entire Library uses a quiet status dot because it is a scope rather than a
countable selection; an empty explicit selection has no indicator. A temporary
passage supplied to one turn may still use a compact, truncated context rail so
the user can identify the text that will be submitted. On phones the Composer
stays one compact row above primary navigation: the
Iconoir AtSign context trigger anchors the left, the input owns the flexible
middle slot, and the circular submit or stop action anchors the right. The
context trigger's accessible name and native title carry the current library,
project, paper, mixed-item, or empty-selection scope. Standard and Deep open
one text-only radio menu from the phone header or desktop Composer instead of a
segmented toggle. The phone menu is a compact two-label list; the desktop menu
retains one supporting description per mode. Decorative mode icons do not
repeat the labels. The trigger indicator is decorative because its accessible
name already announces the complete current scope; it must not create a second
focus target.
Entire Library is mutually exclusive with selected projects and papers. While
it is active, the context picker hides search and item selection rather than
showing controls that cannot affect the scope; switching it off restores the
explicit project and paper chooser.
The shared picker queries Projects and Library papers from the Server whenever
it opens or its search changes. Seed records from the current surface preserve
the active scope label, but they never limit discovery to a route's first page;
large Libraries remain searchable without preloading every paper.
The canonical responsive Composer contract is Figma node
[`923:2628`](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=923-2628),
`Matrix / Composer v2`. It supersedes earlier isolated Composer compositions;
whole-screen frames remain contextual references for the surrounding shell.
Every scope, send, stop, and navigation target remains at least 48 px.
The current bottom-navigation destination is represented by both
`aria-current="page"` and a filled circular icon surface, with a stronger label.
This state is not color-only: shape, weight, and semantics remain distinguishable
in monochrome, Dark appearance, and high-contrast environments.

The shell keeps the mobile workspace aligned to `visualViewport` at all times,
not only while the keyboard is open, so tab switches that expand browser chrome
cannot leave the Dock under the home indicator. When the Composer receives
focus, the shell freezes the pre-focus viewport height and compares it with
`visualViewport.height` to distinguish a soft keyboard from a hardware
keyboard. It deliberately ignores `visualViewport.offsetTop` for the
open/closed decision: Android Chrome changes that value while panning a focused
page, which must not remount the navigation. The offset is still applied as a
shell translation while the keyboard is open, compensating for Chrome's
visual-viewport pan so the Dock remains immediately above the keyboard. A soft
keyboard hides the three-item navigation, removes the Dock's bottom safe-area
padding, and constrains the shell to the focused visible viewport. Navigation
returns only after the visible height recovers or focus leaves the Composer,
without changing the message scroll position. Browsers without `visualViewport`
fall back to hiding navigation while the mobile Composer is focused and to the
layout viewport height for shell sizing.
Markdown is rendered as semantic headings, lists, links, code, and
horizontally scrollable tables; raw HTML is not accepted. Streaming answers
disable `text-pretty` so incomplete lines wrap with the same
`overflow-wrap: anywhere` contract as completed answers; once the stream
settles, pretty balancing returns. Streaming answer candidates use the same
main answer surface as completed answers. Provisional Worklog rows use the same
Markdown primitive with a complete `min-w-0` chain, so long unbreakable titles
or URLs wrap inside their own lane instead of widening the page. The same
messages, stream reducer, context state, and submission logic are used by
desktop and mobile.

The mobile visual baseline is represented by `Home / Workspace / Mobile Empty`,
`Mobile Composer Expanded`, `Mobile Conversation`, `Mobile Conversation Large`,
`Mobile Reasoning Menu Open`, `Mobile Navigation Open`, and `Mobile Processing`, plus
`Conversation View / Mobile Research Answer` in Light and Dark. The acceptance
set covers 390 x 844 and 430 x 932; 320 x 568 is an overflow and
minimum-usability check rather than the primary aesthetic target.

Figma `20 — Home` also records the phone-specific recent-content contract as
`Home / Mobile / Recents populated` (`889:3416`), `Recents loading`
(`889:3456`), `Recents error` (`889:3490`), and `Recents hidden after submit`
(`889:3521`). These frames intentionally use a single compact launcher list
instead of shrinking the desktop paper and project cards. Each launcher keeps
its icon in a fixed slot and gives its title a shrinkable content slot. Long
paper and project titles wrap to at most two lines before clipping; they never
increase the page's horizontal scroll width. The complete title remains the
button's accessible name. In the populated phone composition, the research
prompt and launcher list form one lower-canvas task group immediately above
the composer. The redundant explanatory subtitle is omitted on phones while
remaining available on desktop and in the phone first-run state.

The navigation-open acceptance frame is `Home / Mobile / Navigation open`
(`939:2639`). It fills the viewport with an opaque sidebar surface above a
lower-z backdrop. Account identity and the directional return control stay at
the top, conversation history scrolls in the middle, and Search, Settings, and
New conversation stay fixed above the bottom safe area. Storybook mirrors this
state as `Workspace / Mobile Navigation Open`, including a long account name
and email so truncation and alignment remain executable acceptance criteria.

When both recent-paper and recent-project queries settle empty, Home uses a
focused first-run composition instead of preserving empty card silhouettes.
On phones, its composer sits at the bottom of the usable canvas immediately
above primary navigation; the research prompt remains in the available reading
area rather than pulling the input toward screen center. On desktop, the 760 px
composer retains the centered Figma composition. Its textarea delegates focus
presentation to the rounded composer boundary. Pointer and touch focus leave
that boundary visually stable; keyboard navigation alone receives the shared
semantic focus indicator, so a native rectangular outline never splits the
composition.
The account trigger sits against the sidebar's bottom safe-area inset without a
redundant disclosure arrow. Its menu aligns to the expanded sidebar content
edge and opens to the right of the collapsed rail.
`Workspace / Long Account Identity` preserves the same compact 48 px desktop
row while exercising a long name and email; the mobile navigation story covers
the corresponding 64 px touch row.
On desktop, when only one collection has data, only that section is rendered
and centered; loading and recoverable errors remain visible per collection.
The populated desktop state continues to follow the canonical two-paper and
three-project layout. On phones, papers and projects are merged by recent
activity into at most three compact scope launchers above the Dock. Selecting
one sets the research scope; it does not submit a question. Loading uses the
same short-row footprint, and the entire launcher leaves the composition as
soon as the first message creates a conversation.

The visual acceptance pass also includes a 2560 px wide viewport so the
first-run composition remains intentional on large desktop displays.

Storybook is the isolated state catalog. Playwright covers authenticated route
composition, the context interaction, accessibility, locale selection, and
narrow-screen containment. The real local Server remains the final integration
check.

## Deferred by design

Projects, Reader, Translation, and Settings routes remain disabled navigation
destinations until their own vertical slices begin. Library is now an owned
vertical slice and reuses only the Workspace Shell boundary; Home continues to
own its composer, reasoning control, keyboard behavior, and conversation state.
Home does not edit conversation metadata or add a legacy-client compatibility
layer. Any newly discovered backend gap must block a current Home behavior
before the contract is expanded.

## Motion acceptance

Home preserves spatial continuity when the desktop Sidebar changes width and
when the dashboard becomes an active conversation. Sidebar labels disclose
inside the stable rail; its vertical anchors do not move. An accepted user turn
and bounded Worklog entries enter as one state change, while streamed answer
text remains direct and coalesced rather than animating token by token. Context
Composer resizing is a bounded layout change. Native route navigation and the
whole page never crossfade. Reduced mode commits the same URL, turn, panel, and
focus states without spatial layout animation and moves Jump to latest directly
to its target.
