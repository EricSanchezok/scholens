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
- Reader and Projects detail destinations are not part of Library. Until those
  vertical slices exist, dependent open actions say “Not available yet” and do
  not render a link.
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

Desktop uses a semantic table. Below the desktop breakpoint, Papers uses a
dedicated stacked list rather than compressing the table. Both compositions
offer search, tag filtering, sorting, explicit row actions, selection, and
cursor navigation.

Ingestion jobs are shown only while pending, running, or failed. Polling runs
only while at least one job is unfinished and stops after terminal state.
Failed jobs retain their source and expose Retry. No placeholder paper is
inserted before the canonical query returns it.

Add papers accepts multiple PDF files up to 50 MB each and processes at most
three uploads concurrently. DOI, arXiv, and direct PDF URL are discriminated
source submissions. Each file owns its status and retry action, so one failure
never clears the other files or the source form.

## Outputs

Outputs renders the Server's canonical Research Item projection. The only
supported kinds are `highlight_thread`, `citation`, `audio_overview`, and
`data_table`; the Web neither invents additional output models nor reconstructs
scope permissions from other endpoints. Each item carries its source scope,
source title, and update time from the list response.

Desktop uses a semantic table with fixed column slots. Mobile uses dedicated
stacked cards so type, source, and update metadata remain readable without
compressing the table. Kind filters use a desktop popover and mobile bottom
sheet. Because Reader and Projects destinations are not yet available, the
open affordance is a disabled “Not available yet” action rather than a link,
placeholder route, or temporary preview feature.

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
| processing / failed retry   | `974:2153`, `974:2241`             | `Processing`, `FailedWithRetry`          |
| 390 populated / empty       | `974:2331`, `974:2379`             | `Mobile390`, `Mobile390Empty`            |
| 430 loading / filters       | `974:2410`, `974:2469`             | `Mobile430Loading`, `Mobile430Filters`   |
| 320 error / multi-select    | `974:2438`, `974:2517`             | `Mobile320Error`, `Mobile320MultiSelect` |
| mobile processing / retry   | `974:2571`, `974:2622`             | `Mobile390Processing`, `Mobile390Failed` |
| Add papers desktop / mobile | `979:1831`, `979:1938`             | `AddPapers`, mobile viewport review      |

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
