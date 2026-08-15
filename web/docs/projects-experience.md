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
  reused with `scope_type=project`; Projects does not fork chat behavior. Reader
  and Projects share the Conversation switcher, including search, Pinned and
  Recent groups, current selection, creation, and pinning.
- Papers open Reader at `/reader/[documentId]?project=[projectId]`. Adding
  papers starts from the first item in the Manage Project menu and selects real
  personal Library memberships. A successful add clears paper search and
  cursor state, restores Recently added sorting, and opens the Papers view.
  The Papers tab does not repeat the action. Removing a paper first
  probes the Server's collaborative-annotation impact contract; if Project
  threads exist, the member must confirm the reported thread and comment
  counts before the destructive retry is sent.
- Outputs use the canonical Research Item kinds. Types without a dedicated
  viewer are truthful list rows rather than fake links.
- Archive is not exposed because there is no archived-project collection or
  restore contract. Owners may delete; collaborators may leave.

List search, sort, and cursor live in the URL. Detail view, selected
conversation, chat disclosure, and namespaced paper/output filters also live in
the URL. `panel=chat` means the responsive Project conversation is open;
omitting `panel` fully collapses it without deleting `conversation`. Closing the
panel keeps the mounted draft and selected conversation. Server resources use
TanStack Query; forms use React Hook Form and Zod; dialog and menu disclosure
remains local.

Desktop detail defaults to a flat editorial canvas with no reserved chat rail.
Opening chat adds the same responsive `clamp(23rem, 34vw, 31.25rem)` side panel
used by Reader. Mobile uses a Reader-style full-screen Sheet with dynamic
viewport and safe-area padding; the Workspace app bar remains the only visible
page title, while conversation history and New Conversation keep the same
placement and icons as Reader. Papers and rows become one-column compositions
below the desktop breakpoints, and all controls remain usable at 320px.

Project detail inherits the Library collection language: underlined tabs,
pill-shaped search and sorting controls, quiet separators, local row hover, and
unboxed empty states. Paper, conversation, and output counts live with the
project title metadata instead of in a separate metric card.

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
- `GET /api/v1/projects/{projectId}/papers` supports search, sort, pagination,
  and exposes the Project relationship's `added_at`.
- `GET /api/v1/projects/{projectId}/outputs` applies the same search, kind,
  sort, visibility, and cursor semantics as Library Outputs while restricting
  the collection to one authorized Project.
- `DELETE /api/v1/projects/{projectId}/papers/{documentId}` is attempted
  without confirmation first. A `project_document_has_annotations` conflict
  opens an impact dialog; only the explicit retry sends
  `confirm_delete_annotations=true`.

## Figma and Storybook acceptance

Canonical Figma file: [Scholens — Product Design](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design).

| Acceptance state          | Figma node               | Story                                              |
| ------------------------- | ------------------------ | -------------------------------------------------- |
| list populated / empty    | `330:2`, `333:249`       | `Features/Projects/List` → `Populated`, `Empty`    |
| create project            | `334:608`                | `CreateProject`, `Features/Projects/Project Form`  |
| row actions               | `335:844`                | `Features/Projects/Project Row` owner/collaborator |
| overview, chat collapsed  | `1085:1371`              | `Features/Projects/Detail` → `OverviewCollapsed`   |
| chat expanded             | `1085:1431`              | `ChatExpanded`                                     |
| shared history open       | `1087:1783`              | `ChatExpanded`, Conversation switcher stories      |
| papers populated / empty  | `1087:1538`              | `Papers`, `PapersEmpty`                            |
| outputs populated / empty | `1087:1622`              | `Outputs`, `OutputsEmpty`                          |
| manage / Add papers first | `1087:1715`              | `Papers`                                           |
| mobile 390 project / chat | `1088:1874`, `1088:1918` | `MobileChat` and responsive E2E                    |
| mobile 430 project / chat | `1088:1937`, `1088:1981` | `Mobile430`, `MobileChat`                          |

The list implementation uses a single-column, Library-aligned row composition
instead of the superseded card grid; the active Figma list frames record this
intent. Other intentional differences are the omitted topic chips, “Most
active” sort, Archive action, and Figma-only Report/Note output labels. Runtime
behavior uses the real public contract and accessible responsive composition.

The canonical detail matrix is the Figma section `1085:1370`. The former
56px collapsed-chat rail at `539:7324` is retained only as an explicitly named
Archive frame; it is not an active acceptance state.
The compact desktop list and detail headers are intentional runtime refinements
pending canonical-frame synchronization after local visual acceptance; the
documented responsive and interaction state inventory is unchanged.
