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
- Zotero is a one-way source for a user's personal Zotero library. Library
  never browses Group Libraries or writes Scholens changes back to Zotero.
- The replacement frontend does not import from `client/`, synthesize reports or
  notes, or preserve superseded ingestion contracts.

## State ownership

| State                                                         | Owner                    |
| ------------------------------------------------------------- | ------------------------ |
| active tab, committed query, status/tag/kind filters, sort    | URL search parameters    |
| papers, outputs, summary, tags, projects, ingestion jobs      | TanStack Query           |
| ordered paper columns, column widths, and preview layout      | account preference API   |
| Zotero collections, library pages, operations, status         | TanStack Query           |
| source import fields                                          | React Hook Form + Zod    |
| paper search draft, selected rows, open dialogs, upload queue | feature-local state      |
| Zotero selection                                              | feature-local state      |
| shell collapse and mobile navigation disclosure               | Workspace Shell boundary |

Paper search keeps an editable local draft and submits its trimmed value only
when the user presses Enter; typing never changes the URL or result collection.
The submitted query is the shareable URL state, and requests receive an abort
signal. Output search retains its 250 ms debounce. A filter, sort, or tab
transition clears row selection. Paper browse and search use separate infinite
TanStack queries and progressively append pages as the collection approaches
the viewport; a visible Load more action remains the keyboard, reduced-motion,
and observer fallback. Opaque continuation cursors are never decoded by the
Web. Outputs retain explicit Previous/Next navigation.

Desktop Library chrome is a compact 44 px workbench header: the page title,
Papers/Outputs tabs with counts, and Add papers action share one row. Search,
filters, sorting, result count, preview disclosure, and column management share
one compact utility row after 16 px so research content enters the first
viewport without a repeated explanatory hero or a second controls band.
Explanatory copy belongs to empty and unavailable states. Mobile keeps the
Workspace app bar as the only page-title and primary-action surface.

At phone widths the utility controls stay on one non-wrapping row: search owns
the remaining width while status, tag or kind, and sort collapse to distinct
44 px icon controls with accessible names. Full labels return when the content
width can support them. Result counts already represented by the page tabs are
hidden from the phone utility row instead of creating another line; active
filter counts remain attached to their control.
The utility row itself is a transparent layout region rather than a framed
surface. Search, filters, and sorting each keep one quiet control boundary;
the workbench does not add a second background, border, or shadow around them.
The owned tag catalog is requested when filtering or tag management opens;
assigned tags already present on paper rows remain available without that
catalog request.

## Papers

Desktop uses the shared full-width `paper-collection` workbench: a flat semantic
table with a sticky header, quiet dividers, fixed 64 px virtual rows, and a
page-level details panel that enters from the right beneath the stable Library
title and tabs, then fills the remaining content height. The panel follows the
same spatial model as Project Chat, defaults to 512 px, and can be resized from
400 to 720 px while preserving at least 640 px for the collection. The fixed
page header does not resize when the panel opens or a user changes tabs. The
collection and panel scroll independently when their own content exceeds the
viewport. The virtualized collection body is the only vertical scroll owner on
the Papers surface; page chrome, tabs, search, and filters remain fixed while
continuation pages append, and a terminal downward gesture never chains into
the Workspace page or exposes layout padding below the collection. One persistent,
icon-only eye control in the collection toolbar opens and closes the panel,
changes icon and pressed state with disclosure, and retains focus in place; the
panel does not duplicate that control in its own header. Project Papers keeps
the workbench's inline preview because the Project page-level right rail is
owned by Chat. When either preview is open, selected columns compress together
to panel-specific display minima instead of disappearing by breakpoint. If the
remaining collection width cannot contain them, local horizontal scrolling
keeps every selected column reachable.

Default columns are Paper, Status, Tags, Authors, Publication, and Last opened.
Added and DOI are optional; every column except Paper can be hidden and the
visible columns can be reordered. Column order, per-column widths, preview
width, and preview disclosure are account-scoped and shared with Project Papers;
sort and filters remain URL state. The Paper column can contract to 160 px and
expand to 1,600 px. Dragging an internal column boundary redistributes the
stored bounded width only between its two adjacent visible columns, keeping
their combined width and the trailing column edge fixed; preview compression is
a display projection and is never persisted as an invalid preference. The
boundary stops when either column reaches its limit, and the final data column
has no resize handle. Every paper owns a stable 36×52 px portrait
thumbnail slot that consumes `preview_url` and falls back without shifting the
text columns. A failed short-lived preview URL is remembered by URL, so a newly
signed URL retries automatically in both the row and details preview. Preference
writes are serialized per account preference key; rapid edits preserve their
order, and only server-confirmed data can be a rollback source. Before the
initial query resolves, a failed write restores the documented defaults and
refetches instead of retaining optimistic state. Column move controls name
their target for assistive technology, disable impossible boundary moves, and
keep the popover open for consecutive keyboard reordering. Column header edges
and the table-preview divider expose pointer and keyboard separators with
bounded values; completed adjustments persist once rather than writing on every
pointer movement. Expanding columns beyond the available table space creates a
local horizontal scroller whose header remains aligned with its rows. The column
popover groups visibility and ordering for each column on one row and offers one
reset for all stored widths. Selection remains an independent leading control.
Entering selection replaces the utility row with the batch toolbar above the
collection.

Below 640 px of collection width, Papers uses a compact stacked row rather than
compressing the table. Long titles wrap to at most two lines and uninterrupted
identifiers do not create horizontal page scrolling. Compact mode renders only
its active two-or-three-column semantic structure (named thumbnail, paper
details, and optional row actions), rather than keeping a hidden desktop table;
desktop-only selection controls therefore do not create phantom mobile columns.
When the page-level container is below 1040 px, the preview temporarily becomes
unavailable without rewriting the stored preference; selected desktop columns
remain reachable through the collection's local horizontal scroller. Mobile
exposes neither column management nor preview. Selecting or
focusing a paper updates the preview with its full title, authors, publication,
DOI, personal status, tags, abstract or summary, and keywords. Hover provides a
temporary preview; focus or pointer activation persists the current row so
moving the pointer away does not discard the user's context. Summary Markdown
is rendered as restrained editorial content rather than exposed source syntax.
The preview presents the portrait beside core metadata so the abstract or
summary starts earlier, and never repeats navigation.

Submitting two or more query characters switches the paper collection to the
shared hybrid search contract. Its toolbar remains mounted while the result
region loads, fails, or becomes empty, and search mode presents relevance as a
fixed ordering instead of exposing browse sorts that do not apply. Exact
title/author/DOI matches, whitespace-insensitive and
typo-tolerant matches, full-text passages, and local multilingual semantic
similarity are fused into one relevance order. Results explain why they match
through metadata, abstract/summary context, and bounded snippets. Semantic
index coverage is additive: missing or failed embeddings fall back to lexical
retrieval and never hide otherwise matching papers.

The Library collection uses one flat editorial surface rather than placing a
table inside a rounded card. Search and non-select filters remain compact pills;
sorting uses the same light-line Select surface as forms and Reader. The
table owns one top boundary beneath its utility row. The Library preview owns a
single quiet full-height divider at the page boundary instead of inheriting the
table frame or introducing nested cards. The inline Project preview begins at
the collection boundary and follows the same quiet-divider ownership. Rows are
separated by quiet dividers and reveal a local hover surface. Mobile keeps the
same border ownership with one divided list instead of a stack of repeated
cards. This visual contract also applies to Outputs. Papers and Outputs share
the same full-width page container, header alignment, and responsive padding,
so switching tabs never moves the title, tabs, primary action, or content edges.

Paper and tag rows follow the shared collection-row and nested-action contract
in [Component Development](./component-development.md). The row's main content
region is the only Reader Link; status, tag, selection, column, and overflow
controls are siblings and never trigger navigation. Touch layouts keep overflow
actions visible and never depend on hover.

Reading state is `todo`, `reading`, or `completed` and is editable in place.
Status filters use OR semantics, tag filters use OR semantics, and combining
the two groups uses AND semantics. The default sort remains Recently added;
Last activity is an additional stable keyset sort. Browse and hybrid-search
results share the same rows, preview, personal metadata controls, and filter
semantics. The fixed-height virtualizer retains only the viewport plus overscan
while cursor pagination continues to append logical results, so loading 1,000
papers does not create 1,000 row elements.

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
source, filename, failed lifecycle stage, stable safe error code, Retry, and
remove/cancel actions. The header separates successful Paper count from active
or failed import count and calls out failures that require attention; processing
rows are never counted as successful Papers.

PDF parsing is local-first. A scanned document, or a digital document whose
local engines fail, may require the user's MinerU connection. A missing or
invalid credential is represented as a required integration, not a generic
failure: the row offers Connect MinerU, opens Settings → Connections, and
resumes that one pending retry after a new token is saved. Rate limits and
provider unavailability remain retryable. Insufficient content and unsafe
archives are terminal and do not display a misleading Retry action. A digital
PDF retains the deterministic text-only local fallback when remote rescue is
unavailable.

The client polls only while a visible ingestion is active and stops after a
terminal state. Progress heartbeats and Server-owned deadlines prevent an
indefinite processing row. Cancellation is optimistic in the interface and
cooperative in the worker: a late callback cannot restore a cancelled row.

Add papers accepts multiple PDF files up to 30 MB each and processes at most
three uploads concurrently. A queued file may be removed before upload, and an
in-flight file may be cancelled independently. DOI, arXiv, and direct PDF URL
are discriminated source submissions with inline validation and one visible
pending state. The dialog closes after canonical acceptance; the row that then
appears in Library is the durable acknowledgement. Each file owns its status,
cancel, and retry action, so one failure never clears the other files or the
source form.

DOI import requires the current user's OpenAlex Connection after the DOI passes
local validation. Missing or invalid credentials preserve the field and expose
a Connect OpenAlex action to Settings → Connections; returning requires an
explicit resubmission and never triggers a hidden retry. Rate limiting and
provider unavailability have distinct retry-later copy. Upload, arXiv, and
direct PDF URL paths do not consult OpenAlex, and DOI resolution never swaps in
AnySearch, Tavily, or another web-search connector.

When a network interruption makes the acceptance result unknown, Web retries
or reconciles with the same operation-scoped idempotency key. It never invents
a second key merely because the first HTTP response was lost.

### Import from Zotero

Add papers includes a Zotero entry alongside upload and source URL. When the
account is disconnected it begins OAuth with `intent=import`; a successful
callback restores Library and opens the chooser exactly once. When connected,
the chooser browses the personal Zotero library through server-owned search,
collection and paper-type filtering, sorting, and opaque Previous/Next cursors.
Collection pages are fetched on demand through their own opaque cursor, so
libraries with more than 100 collections expose an explicit “Load more
collections” action instead of silently omitting filters. The Web never
downloads a whole library to filter it locally.

Only `journalArticle`, `conferencePaper`, and `preprint` are selectable.
Entries expose whether they have a stored PDF, a resolvable source, or no
usable source. Already imported, currently processing, and unavailable items
remain visible but disabled. Nothing is selected by default. Selection is
retained while paging and is capped at `min(50, remaining account paper
slots)`; zero capacity is an explicit state rather than a paid-upgrade action.

Submitting creates one idempotent asynchronous import operation and closes the
chooser after Server returns `202`. The operation surface polls its durable
`queued`, `running`, `partial`, `succeeded`, `failed`, or `cancelled` state and
supports cooperative cancellation. It restores the active import from Zotero
status after refresh or navigation and shows worker stages without a fabricated
percentage. Each accepted item
immediately continues through the existing Library ingestion row and PDF
stages; the Zotero batch is progress context, not another paper-row authority.
Partial success preserves successful papers and gives every failed Zotero item
a stable product code without exposing provider exceptions.

Manual Sync now lives in Settings and appends new Zotero annotations only to
papers previously imported through the connection. It does not discover or
import new papers. Automatic import of future Zotero additions is a separate,
default-off Researcher preference.

PDF selection is deduplicated by a browser-computed content digest before the
queue is created; duplicate content is represented once and the skipped count
is announced inline. Server-side SHA-256 reservation checks and collection
uniqueness remain authoritative across tabs, clients, and concurrent requests.
The Papers list projects each personal membership exactly once: an active or
failed ingestion replaces that membership's normal row until the job completes,
rather than appearing as an additional row. An accepted reservation without a
Document is pinned at the beginning of the first forward page until it completes
or the user removes it, so a concurrently accepted second upload cannot vanish
behind Paper pagination.

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

The former Papers section `974:1831` is archived. Current workbench acceptance
lives in section `1172:1885` and maps to
`Features/Paper Collection/Workbench` plus Library ingestion stories:

| Acceptance state             | Figma node                         | Story                                                             |
| ---------------------------- | ---------------------------------- | ----------------------------------------------------------------- |
| desktop Library populated    | `1172:1886`                        | `Library`                                                         |
| Project personal metadata    | `1172:1887`                        | `ProjectPapers`                                                   |
| narrow / mobile              | `1172:1888`, `1172:1889`           | `Narrow`, `Mobile`                                                |
| dark                         | `1172:1890`                        | `Dark`                                                            |
| filters / column management  | `1172:1891`                        | `Library` interaction                                             |
| search snippets              | runtime shared state               | `SearchResults`                                                   |
| 1,000-row virtualization     | runtime performance acceptance     | `ThousandPapers`                                                  |
| desktop empty/loading/error  | `974:1919`, `974:1967`, `974:2012` | `Empty`, `Loading`, `Error`                                       |
| multi-select                 | `974:2060`                         | `MultiSelect`                                                     |
| processing stages / retry    | `974:2153`, `974:2241`             | `Processing`, `FailedWithRetry`                                   |
| desktop cancelling           | `1002:1831`                        | `Cancelling`                                                      |
| 390 populated / empty        | `974:2331`, `974:2379`             | `Mobile390`, `Mobile390Empty`                                     |
| 430 loading / filters        | `974:2410`, `974:2469`             | `Mobile430Loading`, `Mobile430Filters`                            |
| 320 error / multi-select     | `974:2438`, `974:2517`             | `Mobile320Error`, `Mobile320MultiSelect`                          |
| 320 long-title containment   | responsive runtime acceptance      | `Mobile320LongTitles`                                             |
| mobile processing / retry    | `974:2571`, `974:2622`             | `Mobile390Processing`, `Mobile390Failed`                          |
| mobile queued / cancelling   | `1002:1919`, `1002:1970`           | `Mobile390Queued`, `Mobile390Cancelling`                          |
| Add papers desktop / mobile  | `979:1831`, `979:1938`             | `AddPapers`, mobile viewport review                               |
| duplicate PDF selection      | `1007:2`                           | `AddPapersDuplicateSelection`                                     |
| OpenAlex required / narrow   | responsive runtime acceptance      | `AddPapersOpenAlexRequired`, `Mobile320AddPapersOpenAlexRequired` |
| OpenAlex required dark zh-CN | responsive runtime acceptance      | `DarkChineseAddPapersOpenAlexRequired`                            |
| Zotero populated chooser     | Add papers integration intent      | `Features/Zotero/Library/Populated`                               |
| Zotero empty / slow          | responsive runtime acceptance      | `Empty`, `Slow`                                                   |
| Zotero disconnected / error  | responsive runtime acceptance      | `Disconnected`, `RateLimited`                                     |
| Zotero quota / partial       | responsive runtime acceptance      | `ZeroQuota`, `PartialSuccess`                                     |
| Zotero paging + keyboard     | responsive runtime acceptance      | `PaginationSelection`                                             |
| Zotero >100 collections      | provider collection pagination     | `ManyCollections`                                                 |
| Zotero 390 / 320             | Add papers mobile intent           | `Mobile390`, `Mobile320`                                          |
| Zotero Dark Chinese          | localized appearance acceptance    | `DarkChinese`                                                     |
| tag assignment / management  | shared Library interaction state   | `Tag manager dialog` lifecycle stories                            |
| lifecycle behavior contract  | `1002:2021`                        | ingestion-row state stories                                       |

Figma owns visual intent; Storybook owns executable runtime states. Differences
required for responsive composition and accessibility are implemented in code,
not as duplicated Figma-layer mechanics.
The compact desktop workbench header is an intentional runtime refinement
pending canonical-frame synchronization after local visual acceptance; it does
not change the Library state or interaction inventory.

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

## Motion acceptance

Papers replaces its utility row with the selection toolbar in the same layout
slot, then performs only local row continuity. A newly accepted ingestion may
settle into its canonical row; progress uses `scaleX`, and indeterminate loading
uses the shared spinner/skeleton recipes. Filters, sorting, pagination, and tab
navigation do not animate the full collection or stagger long results. Mobile
dialog and sheet movement is primitive-owned. Reduced mode removes toolbar and
row displacement, stops perpetual loading motion, and preserves exact status,
selection, cancellation, and retry behavior.
