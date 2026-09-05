# Projects Experience

Projects is the authenticated workspace for organizing a shared research
question. `/projects` owns discovery and creation; `/projects/[projectId]`
owns overview, papers, outputs, and the contextual Project conversation. The
implementation lives in `src/features/projects` and composes Workspace Shell
and the shared Conversation feature.

## Product and state boundaries

- Project rows show only Server-owned facts: paper count, the current user's
  private Project-conversation count, visible output count, and computed
  activity time. Figma topic chips are omitted because no Project-tag model
  exists.
- Project creation has one primary entry per responsive composition: the page
  header on desktop and the app bar on mobile. Empty and filtered-empty states
  explain the collection state without repeating the creation action.
- Project conversations are private to the current member even though their
  starting scope is the shared Project. The existing Conversation runtime is
  reused with `scope_type=project`; Projects does not fork chat behavior. The
  Project becomes the default research context of a new draft, not a locked
  boundary: the shared `@` context picker stays available so the user may
  narrow or broaden scope, and edits persist like Home (create with
  `paper_context`, then `PUT /api/v1/conversations/{id}/context` before the
  next turn). The picker keeps the current Project as a seed and uses the
  shared server-backed Project and Library search rather than loading a second
  route-local catalog. Reader and Projects share the Conversation switcher,
  including search, Pinned and Recent groups, current selection, creation, and
  pinning; that switcher remains scoped to the current Project.
- The Workspace sidebar conversation history is global on every surface: it is
  never filtered to the current Project, and selecting a session (or opening
  it in a new tab) navigates to the Home conversation workspace at
  `/?conversation=<id>`. Embedded Project chat URLs such as
  `/projects/<id>?conversation=<id>&panel=chat` are entered only through the
  in-panel Conversation switcher and first-send creation, never through the
  sidebar.
- Papers open Reader at `/reader/[documentId]?project=[projectId]`. Adding
  papers starts from the first item in the Manage Project menu and selects real
  personal Library memberships. A successful add clears paper search and
  cursor state, restores Recently added sorting, and opens the Papers view.
  The Papers tab does not repeat the action. Removing a paper first
  probes the Server's collaborative-annotation impact contract; if Project
  threads exist, the member must confirm the reported thread and comment
  counts before the destructive retry is sent.
- Project paper browsing uses the shared full-width, virtualized Paper
  Collection workbench, single compact utility row, continuous list/preview
  boundary, personal metadata filters, progressive continuation, desktop
  preview, and hybrid retrieval language as Library, with the search collection
  restricted to the authorized Project UUID. Status and tags are
  always the current actor's private Library metadata and are labeled “My”. A
  Project-only paper is explicitly “Not in Library” and has no fabricated
  personal state. It does not load the full Project into browser memory or
  implement a route-local search index. In the Papers view, the virtualized
  collection body is the sole vertical scroll owner; Project identity, tabs,
  search, and filters remain fixed while continuation pages append. Overview
  and Outputs retain their normal page scrolling.
- Project Papers and Outputs inherit Library's non-wrapping phone utility row:
  search retains the flexible width while filter, kind, and sort controls use
  their compact icon form. They never expand into vertically stacked control
  bands at 320, 390, or 430 px, and the transparent row never adds an enclosing
  frame around the individual controls.
- The `/projects` discovery row follows the same contract: Search projects and
  Sort projects remain on one line at phone widths, with sorting reduced to its
  labeled 44 px icon trigger and full selected text restored when space allows.
- Outputs use the canonical Research Item kinds. Types without a dedicated
  viewer are truthful list rows rather than fake links.
- Archive is not exposed because there is no archived-project collection or
  restore contract. Owners may delete; collaborators may leave.
- Members with `manage_collaborators` see Manage collaborators in the existing
  Manage Project menu. Its responsive dialog shows the owner, editable member
  permissions, and active invitations. New invitations default to no delegated
  powers. Permission controls never allow a manager to grant a power they do
  not hold. Pending delivery is polled; sent includes delivery time; failed
  provides an explicit new-link action. Remove, revoke, and resend remain
  visible operations rather than optimistic disappearance.
- `/project-invitations/[token]` preserves its path through login. An
  authenticated visit submits one acceptance attempt, replaces the bearer URL
  with the accepted Project on success, offers account switching for recipient
  mismatch, treats expired/revoked/authority failures as terminal, and exposes
  retry only for connection or service failure.

List search and sort live in the URL. The Project-paper search field keeps its
unsubmitted draft in feature-local state and writes the trimmed committed query
to the URL only on Enter. Detail view, selected conversation, chat disclosure,
the Overview insight range, and namespaced paper/output filters also live in the
URL. `range` accepts `7d`,
`30d`, `90d`, or `all`; the default `30d` is omitted. Project and output lists
retain opaque URL cursors; Project-paper continuations live in TanStack Query
and append in place. `panel=chat` means the responsive Project conversation is
open;
omitting `panel` fully collapses it without deleting `conversation`. Closing the
panel keeps the mounted draft and selected conversation. Server resources use
TanStack Query; forms use React Hook Form and Zod; dialog and menu disclosure
remains local.

Normal same-tab entry from `/projects` to a Project records the exact list URL,
source row, and scroll position. Both responsive Project-detail back controls
restore that context; a direct detail visit falls back to the most recent
session Projects root, then `/projects`. Entry from personal Activity instead
returns to that exact Activity range, position, and source Project. Project
paper links create a separate context so Reader returns to the exact Project
view and paper collection.
Modified clicks and source-link copy actions remain canonical. The Workspace
rail keeps its expanded or collapsed preference across Project, Reader, and
other Workspace routes for the current actor and browser session.

Desktop detail defaults to one stable editorial canvas with a flat identity
header and single-layer overview groups, with no reserved chat rail.
Opening chat adds the same responsive `clamp(23rem, 34vw, 31.25rem)` side panel
used by Reader. Mobile uses a Reader-style full-screen Sheet aligned to the
visual viewport height and vertical offset with shared safe-area padding; the
Workspace app bar remains the only visible page title. The in-panel toolbar
runs from conversation history, as its only flexible and widest item, to the
compact label-only reasoning-strength selector, New Conversation, and Collapse.
The existing New Conversation and Collapse glyph buttons keep their behavior
and appearance. Papers and rows become one-column compositions below the
desktop breakpoints, and all controls remain usable at 320px.

Project detail inherits the Library collection language: underlined tabs,
pill-shaped search, the shared light-line Select surface for sorting and kind,
shared framed utility rows, local row hover, and unboxed empty states. Paper,
conversation, output, and member counts live with the project title metadata
instead of in a separate metric card. The Overview and Outputs canvases retain
the same `max-w-6xl` content boundary as Papers. The content canvas, identity
header, equal-width tab triggers, and toolbar origins therefore remain fixed
when switching between Overview, Papers, and Outputs. Papers still uses the
shared table and details preview inside that common boundary.

The Overview tab begins with one full-width research-activity sequence: Mine
and Team metric strips, a dual-track trend, a paper-engagement table, and the
shared activity feed. Recent Outputs and Collaboration then form the editorial
two-column composition on desktop. Each section uses one quiet grouped
background with flat interactive rows; it does not place bordered rows inside
bordered cards. The Collaboration panel shows the complete accepted-member roster
returned by `GET /members`, including the owner, plus the total member count.
Members with `manage_collaborators` also get a quiet Manage action that opens
the existing collaborator dialog. The roster query is shared with that dialog
through the Projects TanStack Query keys, so collaborator changes update both
surfaces without a duplicate member model. Accepted members show their shared
profile avatar when available and otherwise keep the deterministic initial; the
same read-only avatar view is used in the management dialog. Below the desktop breakpoint the
sections stack in one column in reading order: insight summary, trend, paper
engagement, activity, outputs, collaboration.

## Research activity in Project Overview

The Project research-activity sequence ships with
[ADR 0039](../../docs/decisions/0039-first-party-research-activity-ledger.md)
and consumes the real insight and Project-activity contracts. It does not fill
the Overview with fake chart data when a dependency is unavailable. Period
changes refetch an authorized Server projection; the browser never downloads
member sessions and aggregates them locally.

Mine remains a private view for the signed-in member. Its metric strip may show
active-reading estimate, visible time, sessions, active days, substantive
coverage, annotations, and private Project questions. Team shows only anonymous
reading aggregates plus separate canonical counters for papers added, shared
annotations, discussion messages, resolved discussions, and outputs. Those counters
are not summed into a synthetic “shared actions” score. It never reveals
another member's private questions or personal annotations. Effort, process,
and outcome retain separate labels; the interface does not calculate a Project
productivity score.

The team reading strip and series are available only when the selected period
contains at least three contributors. Returned team time is already rounded to
five-minute units. When the threshold is not met, the complete team-reading
layer is replaced by a quiet privacy explanation; zeroes are not drawn because
they would falsely mean no work occurred. There is no member picker,
member-level table, exact team session boundary, contribution ranking, or
reading-time leaderboard. Disabling anonymous contribution affects future
Project attribution without hiding the member's private Mine history.

The trend uses one solid, directly labeled Mine series and one dashed,
directly labeled Team series. Legend text and a keyboard-accessible equivalent
table keep the comparison understandable without color or line style alone.
Points are not smoothed across missing dates, the collection boundary is
visible, and comparison copy is omitted when the previous period is incomplete.

The paper-engagement table prioritizes title, the current actor's active-reading
estimate and substantive coverage, shared annotation and discussion-message counts, and
last activity for the selected period. Mine reading values remain private; the
table contains no per-paper team reading time and never identifies who read the
paper. Selecting a paper opens its Reader Insights panel at
`/reader/[documentId]?project=[projectId]&panel=insights` rather than creating a
second Project-only paper heatmap. Sort controls have text labels and do not
imply that duration is paper quality.

The shared activity feed is an authorized chronological projection of facts
already visible to Project members: papers added, members joined, Project-
audience annotations and discussion messages, outputs, and resolved discussions. It may
identify the author of a shared action because that canonical resource already
does. It never emits “member read page” events, session
boundaries, private conversation activity, or personal annotations. Feed rows
carrying an authorized canonical document identifier link to that paper's
Reader Insights panel. Rows without a safe document destination remain plain
chronological facts in the first release; the client does not infer a
destination from an activity kind or private identifier. Feed rows do not
duplicate or mutate the underlying resources.

Mine includes one Remove my Project contribution data control. After an
explicit confirmation it deletes only this actor's Project-attributed reading
rollups; the same sessions remain in private personal insight, and no paper,
annotation, comment, output, conversation, membership, or other member's data
changes. A later eligible Project-context reading session may contribute again
when the anonymous-contribution preference remains enabled. The action is not
worded as Leave Project or Clear personal history.

Desktop Projects uses the same compact workbench density as Library. The list
title and New project action share a 44 px row, followed by search and sorting
after 16 px; introductory copy belongs to empty states. Project detail keeps
Back, title, counts, and management actions in one compact header, renders only
a real description on one line, and places tabs 16 px below it. Mobile retains
the Workspace app bar and existing full-width composition.

Project rows and Project-detail paper rows follow the shared collection-row
and overflow contract in [Component Development](./component-development.md).
Each row has one primary Link for its content region; its menu remains an
independent action target and is always discoverable on touch layouts.

## API contract

- `GET /api/v1/projects` supports `q`, `sort`, signed bidirectional `cursor`,
  and `limit`; it returns one aggregate projection without per-project count
  queries.
- Project activity is the latest relevant Project metadata, paper membership,
  current-member conversation, or visible Project output timestamp.
- `GET /api/v1/projects/{projectId}/papers` supports browse sorting, actor-owned
  `personal_statuses` / `personal_tag_ids` filters, personal activity sorting,
  and keyset pagination. It exposes `preview_url`, summary, keywords, and the
  current actor's optional personal status, tags, and last-access timestamp in
  addition to the Project relationship's `added_at`. Filtering happens before
  count and pagination. Submitting a query of two or more characters uses
  `POST /api/v1/search/papers` with the same personal filters and a Project
  selection collection so fuzzy, full-text, and semantic ranking stay shared.
  The mounted search toolbar remains available in loading, error, empty, and
  populated states, and active search is always presented as relevance-ordered;
  clearing the query restores the prior browse sort.
  Preview and source-file URL signing are independent: the Web requests
  `load_preview_urls=true` and leaves `load_urls=false`, while omitted flags and
  MCP access sign neither URL. Both flags participate in cursor validation.
- `GET /api/v1/projects/{projectId}/outputs` applies the same search, kind,
  sort, visibility, and cursor semantics as Library Outputs while restricting
  the collection to one authorized Project.
- `GET /api/v1/projects/{projectId}/insights` accepts the selected
  `range` and returns the current member's private projection plus a separately
  suppressible anonymous team projection. Project insight dates and period
  aggregation use UTC; finite windows include UTC-hour ledger buckets rather
  than claiming millisecond-exact boundaries. The response includes collection
  and completeness boundaries; the Web does not infer pre-launch history.
- `GET /api/v1/projects/{projectId}/activity` returns the authorized shared
  Project-fact feed. It is derived from canonical paper, Project-audience
  research-item/comment, and collaborator records rather than a copied activity
  table.
- `DELETE /api/v1/projects/{projectId}/me/reading-activity` removes only the
  current actor's Project attribution. It preserves the actor's private reading
  history and every canonical shared Project fact.
- `DELETE /api/v1/projects/{projectId}/papers/{documentId}` is attempted
  without confirmation first. A `confirmation_required` conflict returns the
  exact annotation impact and a short-lived state-bound token. The dialog
  presents that impact; only the explicit retry sends the token in
  `X-Scholens-Confirmation-Token`. A stale, changed, or reused token fails
  without deleting anything.
- `GET /members` and `GET /invitations` supply the collaborator dialog;
  member permission mutation, removal, invitation creation, resend, and revoke
  use their generated public contracts. Invitations expose
  `delivery_status=pending|sent|failed` and optional `delivered_at`.
- `POST /api/v1/project-invitations/{token}/accept` returns
  `{ project_id }`, allowing the route to clear the token with
  `router.replace` before entering the Project.

## Figma and Storybook acceptance

Canonical Figma file: [Scholens — Product Design](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design).

| Acceptance state                            | Figma node               | Story                                                       |
| ------------------------------------------- | ------------------------ | ----------------------------------------------------------- |
| list populated / empty                      | `330:2`, `333:249`       | `Features/Projects/List` → `Populated`, `Empty`             |
| create project                              | `334:608`                | `CreateProject`, `Features/Projects/Project Form`           |
| row actions                                 | `335:844`                | `Features/Projects/Project Row` owner/collaborator          |
| overview, chat collapsed                    | `1085:1371`              | `Features/Projects/Detail` → `OverviewCollapsed`            |
| chat expanded                               | `1085:1431`              | `ChatExpanded`                                              |
| shared history open                         | `1087:1783`              | `ChatExpanded`, Conversation switcher stories               |
| papers populated / empty                    | `1172:1887`              | `Features/Paper Collection/Workbench` → `ProjectPapers`     |
| paper narrow / mobile / dark                | `1172:1888`–`1172:1890`  | `Narrow`, `Mobile`, `Dark`                                  |
| paper filters / columns / folded preview    | `1172:1891`              | `Library` interaction and account preference states         |
| outputs populated / empty                   | `1087:1622`              | `Outputs`, `OutputsEmpty`                                   |
| manage / Add papers first                   | `1087:1715`              | `Papers`                                                    |
| mobile 390 project / ordered chat toolbar   | `1088:1874`, `1088:1918` | `MobileChat` and responsive E2E                             |
| mobile 430 project / ordered chat toolbar   | `1088:1937`, `1088:1981` | `Mobile430`, `MobileChat430`                                |
| collaborator delivery states                | `1151:2`                 | `Features/Projects/Manage collaborators` → `DeliveryStates` |
| collaborator 390 / 320 dark zh-CN           | `1154:2`, `1154:74`      | `Mobile390`, `SmallMobile320`, `ChineseDark`                |
| invitation desktop states / 430 zh-CN retry | `1152:2`, `1154:98`      | `Features/Projects/Accept invitation`                       |

The list implementation uses a single-column, Library-aligned row composition
instead of the superseded card grid; the active Figma list frames record this
intent. Other intentional differences are the omitted topic chips, “Most
active” sort, Archive action, and Figma-only Report/Note output labels. Runtime
behavior uses the real public contract and accessible responsive composition.

The research-activity runtime acceptance adds Mine-only, published Team,
privacy-suppressed Team, partial-history, recording-disabled, trend-table,
paper-engagement, activity-feed, mobile, and Dark states in Project Detail
Storybook and E2E coverage. No stable research-activity Figma node is recorded
yet; this document and the executable states own that behavior until the
canonical Project matrix is synchronized. Reviewers must not cite an unrelated
frame as substitute evidence.

The canonical detail matrix is the Figma section `1085:1370`. The former
56px collapsed-chat rail at `539:7324` is retained only as an explicitly named
Archive frame; it is not an active acceptance state.
The compact desktop list and flat detail headers are intentional runtime
refinements pending canonical-frame synchronization after local visual
acceptance; the same applies to the shared detail column, the members metric,
the two-column Overview with its Collaboration strip, and the collapsed-then-expandable
permission summary in the collaborator dialog. The documented responsive and
interaction state inventory is unchanged.

## Motion acceptance

Project list changes use bounded row presence and position continuity. Opening
desktop Project Chat introduces the contextual side panel and lets the detail
region resize with the shared layout transition; closing it reverses that
relationship without clearing the selected conversation or draft. Mobile Chat
delegates entrance and exit to the shared full-height Sheet recipe. Tabs,
filters, and route navigation do not crossfade the whole page. Reduced mode
opens and closes both chat compositions without spatial movement while
preserving URL state and focus return.
