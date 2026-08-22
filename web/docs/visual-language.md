# Scholens visual language

Scholens is a focused research studio: quiet enough for long reading sessions,
but structured enough that navigation, tools, collections, and working context
are recognizable at a glance. Reader is the layout-quality baseline. The Home
Composer is the control-shape baseline. The account menu and Settings establish
the expected density and information hierarchy.

This guide owns the shared visual rules and the external-recipe mapping. Feature
experience guides continue to own product behavior and state.

## Surface hierarchy

Use the semantic surface according to its job:

| Role               | Token or utility                   | Use                                            |
| ------------------ | ---------------------------------- | ---------------------------------------------- |
| Application canvas | `bg-canvas`                        | Route background and document workspace        |
| Navigation chrome  | `bg-sidebar`                       | Desktop rail and mobile navigation sheet       |
| Structural frame   | `bg-subtle`                        | Groups related panels without claiming focus   |
| Working surface    | `bg-surface`                       | Rows, cards, forms, and primary content panels |
| Elevated surface   | `bg-elevated` plus semantic shadow | Menus, popovers, dialogs, and floating tools   |

Light appearance uses a warm off-white canvas under white working surfaces so
the interface is no longer a collection of white regions separated by faint
rules. Dark appearance keeps a wider dark-end separation. Borders communicate
structure or state; shadows communicate elevation. Do not add both merely to
make a component look stronger.

`Frame` groups one or more `FramePanel` surfaces. Its inner radius is calculated
from the outer radius and inset, so nested corners stay concentric. Product
semantics remain on the child element through `asChild`; Frame never turns a
list, article, navigation region, or table into a generic Item.

## Shape and density

- Composer and mobile quick actions may use `radius-full`; this is the product's
  distinctive high-affordance control shape.
- Workspace panels and grouped collections use `radius-xl` or `radius-2xl`.
- Controls and rows use `radius-lg`; small badges remain full pills.
- Adjacent controls use the existing 36 px desktop / 44 px touch density.
- A section uses 8–12 px within a group and at least 20–24 px between groups.
- Selected navigation and current records use a surface, structure border, and
  restrained raised shadow together. Inactive peers remain quiet.

## External recipe mapping

Registry names identify source recipes to inspect. They are not instructions to
install the block unchanged.

| Scholens surface                              | ReUI source references                           | Adaptation                                                                                                                                                           |
| --------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Workspace rail and mobile navigation          | `c-navigation-menu-3`, `c-item-4`                | Keep the feature-owned shell, Iconoir glyphs, conversation history, collapse animation, URL state, and mobile sheet; adopt framed active rows and clear icon tiles.  |
| Account menu                                  | `c-dropdown-menu-9`, `c-dropdown-menu-14`        | Preserve live usage, public links, focus order, and Settings routing; retain the compact identity header and framed usage summary.                                   |
| Home Composer                                 | `c-input-group-34`                               | Preserve the rounded single-line contract, context picker, reasoning selector, IME handling, and mobile keyboard behavior.                                           |
| Home recents                                  | `c-card-7`, `c-item-6`, `frame`                  | Give each paper or project one outline. Separate preview and metadata with one divider; use fill, not another border, for project icon tiles.                        |
| Library papers and outputs                    | `c-tabs-7`, `c-item-6`, `c-dropdown-menu-12`     | Keep semantic table/list collections, column preferences, bulk selection, preview, filters, and URL state; frame the workbench and strengthen current-row hierarchy. |
| Projects list and detail                      | `c-item-4`, `c-item-6`, `c-tabs-7`, `c-dialog-3` | Use framed rows, metric chips, and a stable detail header; retain real project capabilities and confirmation behavior.                                               |
| Settings                                      | `c-tabs-4`, `c-item-11`, `c-dropdown-menu-9`     | Retain the existing dialog architecture; unify panel sections, integration rows, meters, and mobile panel selection.                                                 |
| Reader annotations                            | `c-item-12`, `c-dropdown-menu-12`, `c-alert-10`  | Keep Reader layout, anchors, audiences, and selection behavior; strengthen thread grouping, quoted evidence, replies, and status surfaces.                           |
| Authentication                                | `c-input-group-1`, `c-card-7`, `frame`           | Keep the authentication contract and public links; place the form in a focused framed surface without marketing decoration.                                          |
| Empty, loading, error, and unavailable states | `c-alert-10`, `c-skeleton-1`, `frame`            | Use one orientation, one recovery action, stable geometry, and semantic status roles.                                                                                |

ReUI Pro application shells and feature blocks are not implementation inputs
without an explicit license. Public descriptions may inform comparison, but
source must be available before code is adapted.

## React Bits boundary

React Bits is useful only where an infrequent transition explains hierarchy.
Candidates are `FadeContent-TS-TW` or `AnimatedContent-TS-TW` for a first-time
empty-to-populated transition or a bounded panel entrance. Prefer the existing
Scholens motion recipes when they already express the same relationship.

Do not use cursor effects, particle bursts, continuously animated backgrounds,
glare, magnetic controls, text scrambling, or autoplay decoration in product
workspaces. Accepted motion must use the existing preference provider, stop in
Reduced mode, avoid first-render animation, and leave a static state cue.

## Responsive contract

- Desktop keeps the persistent navigation rail and frames bounded work regions.
- Tablet collapses secondary regions before compressing primary content.
- At 320, 390, and 430 px, navigation and contextual tools use full-height or
  bottom-sheet patterns with safe-area padding; collection rows become stacked
  summaries rather than horizontally squeezed tables.
- The mobile Composer floats above the canvas. Bottom navigation stays inside
  the safe-area Dock but has no surrounding pill, border, or shadow; its icon
  and label targets remain individually interactive rather than becoming an
  edge-to-edge gray strip.
- Long English, Simplified Chinese, realistic paper titles, loading, empty,
  error, disabled, and keyboard-open states are acceptance, not follow-up work.

## Acceptance

Every visual slice is accepted only after its relevant Storybook matrix covers
desktop, 320/390/430 px, Light, Dark, keyboard focus, long content, loading,
empty, error, and unavailable states. Run token, architecture, design, i18n,
type, unit, Storybook, build, and responsive E2E gates in proportion to the
slice, then run the full Web lane before the visual-system goal is complete.
