# Library Experience

Library is the authenticated workspace for organizing papers and the research
outputs created from them. The route is `/library`; its UI is owned by
`src/features/library` and composes the shared Workspace Shell without importing
Home's conversation or composer implementation.

## Product boundaries

- Papers are personal Library memberships over canonical documents. Removing a
  paper removes only the current actor's membership; project references remain.
- Outputs are Server-projected Research Items visible through personal, paper,
  and project scope. The Web does not infer permissions or join scopes.
- Reader and Projects remain separate feature slices. Library output rows do
  not invent a viewer when their canonical kind has no dedicated destination.
- The replacement frontend does not import from `client/`, synthesize reports or
  notes, or preserve superseded ingestion contracts.

## State ownership

| State                                                        | Owner                    |
| ------------------------------------------------------------ | ------------------------ |
| active tab, query, tag/kind filters, sort, cursor            | URL search parameters    |
| papers, outputs, summary, tags, projects, ingestion jobs     | TanStack Query           |
| source import fields                                         | React Hook Form + Zod    |
| selected rows, open menu/dialog/sheet, per-file upload queue | feature-local state      |
| shell collapse and mobile navigation disclosure              | Workspace Shell boundary |

Search is debounced by 250 ms and query requests receive an abort signal. A
filter, sort, tab, or page transition clears row selection. Cursor navigation is
Previous/Next only; cursors are opaque and never decoded by the Web.

## Papers

Desktop uses a semantic table. Its search, user-tag filter, sort, and result
count share one utility row. Every paper owns a stable portrait thumbnail slot
that consumes the Server-provided `preview_url` and falls back to a document
preview without shifting the text columns. The selection control reuses that
same slot: on pointer devices it appears on row hover or keyboard focus and
remains visible while selected. It is not a permanently visible checkbox
column. Entering selection replaces the utility row with a batch toolbar above
the collection. Both desktop toolbars occupy the same 44 px layout slot so the
collection does not move when selection starts. Batch actions are never placed
in a detached bar below the list.

Below the desktop breakpoint, Papers uses a dedicated stacked list rather than
compressing the table. Mobile has no hover dependency: the row action menu
starts selection, after which thumbnail slots expose checkboxes and the compact
batch toolbar remains above the collection. Titles wrap to at most two lines,
authors and institutions stay on one clipped secondary line, and added and
published dates stay in the same content column immediately after the paper's
text metadata. They are not positioned beneath the full thumbnail row. Long
titles and uninterrupted identifiers must not create horizontal page
scrolling; desktop table titles remain a single line.

Library tags are explicit user-owned organizational labels, not model-generated
keywords. Papers without assigned labels show no synthetic tags; the filter
only lists labels the user owns, and assigned labels render with the paper.
The tag manager owns the full label lifecycle: create, rename, delete, and exact
assignment replacement. Saving an empty selection clears a paper's labels.
Direct batch assignment from Library is not part of this slice. Papers are
added from a Project's real Library chooser; Library does not duplicate that
mutation lifecycle with a second provisional dialog.
The manager uses the shared responsive Dialog structure: a contained desktop
dialog and a safe-area-aware mobile bottom sheet with one scrolling body and a
fixed action footer. It never reserves blank space to resemble a chooser.

An accepted ingestion is a first-class row in the same desktop table or mobile
paper list as completed papers; it is never rendered as a detached status
banner. `uploading` is local-only. The Server's atomic `202` response begins the
canonical lifecycle at `queued`, after which `parsing`, `extracting`, `indexing`,
and `finalizing` update that row without changing its identity or layout.
Completed ingestion becomes a normal paper row. Failed ingestion preserves its
source, stable error code, Retry, and remove/cancel actions.

The client polls only while a visible ingestion is active and stops after a
terminal state. Progress heartbeats and Server-owned deadlines prevent an
indefinite processing row. Cancellation is optimistic in the interface and
cooperative in the worker: a late callback cannot restore a cancelled row.

Add papers accepts multiple PDF files up to 50 MB each and processes at most
three uploads concurrently. A queued file may be removed before upload, and an
in-flight file may be cancelled independently. DOI, arXiv, and direct PDF URL
are discriminated source submissions with inline validation and one visible
pending state. The dialog closes after canonical acceptance; the row that then
appears in Library is the durable acknowledgement. Each file owns its status,
cancel, and retry action, so one failure never clears the other files or the
source form.

When a network interruption makes the acceptance result unknown, Web retries
or reconciles with the same operation-scoped idempotency key. It never invents
a second key merely because the first HTTP response was lost.

PDF selection is deduplicated by a browser-computed content digest before the
queue is created; duplicate content is represented once and the skipped count
is announced inline. Server-side SHA-256 reservation checks and collection
uniqueness remain authoritative across tabs, clients, and concurrent requests.
The Papers list projects each personal membership exactly once: an active or
failed ingestion replaces that membership's normal row until the job completes,
rather than appearing as an additional row.

## Outputs

Outputs renders the Server's canonical Research Item projection. The only
supported kinds are `annotation_thread`, `citation`, `audio_overview`, and
`data_table`; the Web neither invents additional output models nor reconstructs
scope permissions from other endpoints. Each item carries its source scope,
source title, and update time from the list response.

Desktop uses a semantic table with fixed column slots. Mobile uses dedicated
stacked cards so type, source, and update metadata remain readable without
compressing the table. Search, kind filter, sort, and count use the same
responsive utility-row contract as Papers. Kind filters use a desktop popover
and mobile bottom sheet. Kinds without a dedicated viewer keep a disabled “Not
available yet” action rather than linking to a placeholder route or temporary
preview feature.

## Responsive and feedback contract

The primary mobile acceptance widths are 390 and 430 px; 320 px is the minimum
containment check. Sticky controls respect dynamic viewport height and safe-area
insets through Workspace Shell. Desktop popovers become bottom sheets on phones.
Pending, success, error, destructive confirmation, and retry behavior reuse the
repository action-feedback contract and semantic tokens.

## Figma and Storybook acceptance

Canonical Figma file: [Scholens — Product Design, Library](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=214-2).

Papers acceptance lives in section `974:1831` and maps to
`Features/Library/Papers` stories:

| Acceptance state            | Figma node                         | Story                                    |
| --------------------------- | ---------------------------------- | ---------------------------------------- |
| desktop populated           | `974:1834`                         | `Populated`                              |
| desktop empty/loading/error | `974:1919`, `974:1967`, `974:2012` | `Empty`, `Loading`, `Error`              |
| multi-select                | `974:2060`                         | `MultiSelect`                            |
| processing stages / retry   | `974:2153`, `974:2241`             | `Processing`, `FailedWithRetry`          |
| desktop cancelling          | `1002:1831`                        | `Cancelling`                             |
| 390 populated / empty       | `974:2331`, `974:2379`             | `Mobile390`, `Mobile390Empty`            |
| 430 loading / filters       | `974:2410`, `974:2469`             | `Mobile430Loading`, `Mobile430Filters`   |
| 320 error / multi-select    | `974:2438`, `974:2517`             | `Mobile320Error`, `Mobile320MultiSelect` |
| 320 long-title containment  | responsive runtime acceptance      | `Mobile320LongTitles`                    |
| mobile processing / retry   | `974:2571`, `974:2622`             | `Mobile390Processing`, `Mobile390Failed` |
| mobile queued / cancelling  | `1002:1919`, `1002:1970`           | `Mobile390Queued`, `Mobile390Cancelling` |
| Add papers desktop / mobile | `979:1831`, `979:1938`             | `AddPapers`, mobile viewport review      |
| duplicate PDF selection     | `1007:2`                           | `AddPapersDuplicateSelection`            |
| tag assignment / management | shared Library interaction state   | `Tag manager dialog` lifecycle stories   |
| lifecycle behavior contract | `1002:2021`                        | ingestion-row state stories              |

Figma owns visual intent; Storybook owns executable runtime states. Differences
required for responsive composition and accessibility are implemented in code,
not as duplicated Figma-layer mechanics.

Outputs acceptance lives in section `984:1831` and maps to
`Features/Library/Outputs` stories:

| Acceptance state             | Figma node                         | Story                                |
| ---------------------------- | ---------------------------------- | ------------------------------------ |
| desktop populated            | `984:1834`                         | `Populated`                          |
| desktop empty/loading/error  | `984:1938`, `984:1986`, `984:2031` | `Empty`, `Loading`, `Error`          |
| desktop filtered             | `984:2079`                         | `Filtered`                           |
| dark Simplified Chinese      | desktop populated layout           | `DarkChinese`                        |
| 390 populated                | `984:2183`                         | `Mobile390`                          |
| 430 filters sheet            | `984:2239`                         | `Mobile430Filters`                   |
| 390 empty / 430 loading      | `984:2287`, `984:2318`             | `Mobile390Empty`, `Mobile430Loading` |
| 320 error                    | `984:2346`                         | `Mobile320Error`                     |
| archived superseded concepts | `984:2377`                         | not an executable acceptance state   |

The archived section contains the former Reports, Notes, Recently opened, and
page-number concepts. It is retained only as design history and is not a code
or contract target.
