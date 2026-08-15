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
  reused with `scope_type=project`; Projects does not fork chat behavior.
- Papers open Reader at `/reader/[documentId]?project=[projectId]`. Adding
  papers selects real personal Library memberships. Removing a paper first
  probes the Server's collaborative-annotation impact contract; if Project
  threads exist, the member must confirm the reported thread and comment
  counts before the destructive retry is sent.
- Outputs use the canonical Research Item kinds. Types without a dedicated
  viewer are truthful list rows rather than fake links.
- Archive is not exposed because there is no archived-project collection or
  restore contract. Owners may delete; collaborators may leave.

List search, sort, and cursor live in the URL. Detail view, selected
conversation, mobile chat disclosure, and namespaced paper/output filters also
live in the URL. Server resources use TanStack Query; forms use React Hook Form
and Zod; dialog and menu disclosure remains local.

Desktop detail keeps Project chat in a 26rem side panel. On mobile, `panel=chat`
replaces the detail canvas with the full-height conversation surface so the
Reader-style panel is never compressed beside the content. Papers and rows
become one-column compositions below the desktop breakpoints, and all controls
remain usable at 320px.

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

| Acceptance state          | Figma node                    | Story                                              |
| ------------------------- | ----------------------------- | -------------------------------------------------- |
| list populated / empty    | `330:2`, `333:249`            | `Features/Projects/List` → `Populated`, `Empty`    |
| create project            | `334:608`                     | `CreateProject`, `Features/Projects/Project Form`  |
| row actions               | `335:844`                     | `Features/Projects/Project Row` owner/collaborator |
| overview + chat           | `528:542`                     | `Features/Projects/Detail` → `OverviewWithChat`    |
| papers populated / empty  | `530:1036`, `530:1159`        | `Papers`, `PapersEmpty`                            |
| outputs populated / empty | `532:729`, `532:970`          | `Outputs`, `OutputsEmpty`                          |
| manage and edit           | `533:945`, `540:1179`         | runtime detail menu and Project Form stories       |
| mobile chat disclosure    | responsive runtime acceptance | `MobileChat`                                       |

The list implementation uses a single-column, Library-aligned row composition
instead of the superseded card grid; the active Figma list frames record this
intent. Other intentional differences are the omitted topic chips, “Most
active” sort, Archive action, and Figma-only Report/Note output labels. Runtime
behavior uses the real public contract and accessible responsive composition.
