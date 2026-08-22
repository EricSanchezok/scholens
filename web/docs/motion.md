# Motion system

Motion in Scholens explains state, hierarchy, spatial continuity, or progress.
It is not page decoration. The default character is calm and direct: controls
answer quickly, overlays establish their origin, and larger layout changes
settle without bounce. Ordinary route navigation never receives a full-page
transition.

Persistent navigation chrome also mounts without an entrance animation, even
when a route owns a fresh shell instance. Sidebar labels may use
`settled-content-enter` only when the user explicitly expands a collapsed rail;
changing the active route must not replay that reveal across the navigation group.

## Architecture

```text
tokens/motion.json
  -> generated/motion.css + generated/motion-metadata.ts
  -> motion-recipes.css                 (CSS-first primitive behavior)
  -> motion-config.ts                   (shared runtime transitions/variants)
  -> MotionProvider                     (global preference + root CSS policy)
  -> MotionRuntimeProvider              (route-scoped MotionConfig + LazyMotion)
  -> shared primitives and feature choreography
```

The repository owns one motion language and one optional runtime. Product code
inside a runtime-enabled route imports `m`, `AnimatePresence`, variants, and
transitions only from `@/design-system/motion`. Direct `motion/*` imports, raw
Tailwind `duration-*`/`ease-*`/`animate-*` utilities, arbitrary millisecond
values, and page-local keyframes are rejected by `pnpm design:check` outside
the motion foundation.

The root `Providers` tree imports the lightweight `MotionProvider` module
directly. It must not import `motion/react`, the design-system motion barrel,
or `MotionRuntimeProvider`: doing so places the runtime in every route's
initial graph. Library, Projects, Project Detail, and Reader opt in through a
route-local `MotionRuntimeProvider`; Home, Conversation, Settings,
Authentication, and the Workspace Shell remain CSS/WAAPI-first. The design
checker enforces this initial-route boundary.

Use CSS for controls, Radix overlays, progress, spinners, skeletons, and other
single-node state changes. Radix keeps content mounted while CSS exit keyframes
run and exposes `data-state` and collision-aware `data-side`, so introducing a
JavaScript lifecycle for these primitives adds no value. Use the Motion runtime
only when React mount/unmount or measured layout continuity is the behavior:

- a bounded list insert, remove, or reorder;
- one product panel entering or leaving an existing composition;
- a toolbar or content state replacing another in the same region;
- a container resizing around user-controlled content.

Do not use runtime motion for color feedback, ordinary hover, every table row,
continuous PDF pages, long virtualized collections, or route-level crossfades.

## Token contract

| Role         | Value  | Intended use                                       |
| ------------ | ------ | -------------------------------------------------- |
| `instant`    | 0 ms   | Explicit no-motion state                           |
| `feedback`   | 90 ms  | Press, color, border, and compact control feedback |
| `fast`       | 140 ms | Tooltip, popup, and exit                           |
| `standard`   | 220 ms | Dialog, content swap, and ordinary entrance        |
| `slow`       | 320 ms | Mobile sheet and larger bounded surface            |
| `deliberate` | 440 ms | Rare focal content that must be tracked            |

| Easing     | Cubic Bézier     | Meaning                              |
| ---------- | ---------------- | ------------------------------------ |
| `enter`    | `.16, 1, .3, 1`  | Arrive quickly and settle            |
| `standard` | `.2, 0, 0, 1`    | Neutral feedback and continuity      |
| `exit`     | `.4, 0, 1, 1`    | Leave faster than the matching enter |
| `in-out`   | `.65, 0, .35, 1` | Symmetric bounded progress           |

Runtime layout motion uses one responsive spring (`stiffness: 360`, `damping:
34`, `mass: .85`) and one gentler spring (`280`, `30`, `.9`). Their three
parameters are DTCG numeric tokens under `motion.spring.*`; token generation
assembles the typed runtime metadata because DTCG has no portable compound
spring type. Feature code consumes the semantic transition and does not tune a
new spring to make one screen feel different. Continuous spinner and skeleton
cycles are multiples of the deliberate duration token; they stop in reduced
mode.

## Semantic recipes

| Recipe                     | Owner and behavior                                                 |
| -------------------------- | ------------------------------------------------------------------ |
| `motion-control`           | Shared color/border/opacity feedback                               |
| `motion-pressable`         | Restrained press scale for an atomic semantic button or link       |
| `motion-icon`              | A glyph changing direction or state                                |
| `motion-shape`             | Border-radius changes in expanding controls                        |
| `motion-rail-chrome`       | Clipped rail chrome paired with a bounded content-translation FLIP |
| `motion-popup`             | Tooltip, popover, menu, and Select from collision-aware origin     |
| `motion-overlay`           | Dialog or Sheet scrim fade                                         |
| `motion-dialog`            | Centered modal entrance/exit                                       |
| `motion-responsive-bottom` | Bottom sheet on narrow screens, centered dialog on desktop         |
| `motion-responsive-full`   | Full-screen mobile dialog, centered desktop dialog                 |
| `motion-side-sheet`        | Right-origin side panel                                            |
| `motion-side-sheet-left`   | Left-origin navigation panel                                       |
| `motion-toast`             | Brief status surface without changing document layout              |
| `motion-progress`          | GPU-friendly `scaleX` progress                                     |
| `motion-spinner`           | Indeterminate activity; stopped under reduced motion               |
| `motion-skeleton`          | Quiet loading pulse; stopped under reduced motion                  |
| `settled-content-enter`    | One-time result or terminal-state arrival                          |

The runtime exports four variants: `swap`, `listItem`, `panel`, and `focal`.
Choose the semantic result, not the closest-looking transform. `AnimatePresence`
owns exit choreography; `layout="position"` is preferred for list movement and
`layout="size"` for a bounded container. Runtime list motion is capped at the
first six transient items in a local change set; at most those six receive a
24 ms stagger, capped at 144 ms. Canonical paginated rows, including Library
papers, never receive per-row runtime layout motion when sorting or paging.
`Features/Library/Paper ingestion rows/Bounded large queue` exercises ten rows
and asserts that only six carry the runtime marker.

Presence is non-blocking: state and focus commit before the visual transition.
Use `popLayout` or the default synchronous mode for replacement surfaces; do
not use `mode="wait"` for product panels, toolbars, or actionable content.
`MotionPresence` makes an exiting visual layer immediately inert and hidden
from assistive technology so only the newly committed state remains actionable.

## Product choreography

| Surface           | Motion responsibility                                                   |
| ----------------- | ----------------------------------------------------------------------- |
| Workspace shell   | WAAPI FLIP preserves rail continuity without interpolating layout width |
| Home/conversation | CSS state arrival for dashboard swap, accepted turn, and Worklog        |
| Library           | Utility-to-selection toolbar and at most six transient ingestion rows   |
| Projects          | List continuity and Project Chat side-panel expansion                   |
| Reader            | Context/outline panel disclosure, bounded active-panel and toolbar swap |
| Settings          | CSS active-panel replacement and preference preview                     |
| Authentication    | CSS result state settles inside one persistent auth surface             |

Streaming text itself is not animated character by character. PDF canvases and
Reader pages never animate during scroll. Search and selection move directly
to user-requested locations. Motion may preserve the surrounding panel or row,
but must never delay data availability, focus, or the next action.

## Preference and accessibility

The root contract is:

```html
<html data-motion-preference="system" data-motion="full"></html>
```

The Settings choices are `system`, `reduced`, and `full`; the durable key and
cookie are both `scholens-motion`. An inline initialization script resolves the
choice before paint, with local storage taking precedence over the cookie.
Storage access is fail-safe: if browser policy rejects local storage, the
initializer continues through the cookie and system media query, and a failed
write never blocks the in-memory preference or cookie attempt. `system`
delegates the runtime policy to Motion's user preference and listens to
`(prefers-reduced-motion: reduce)`; the CSS media fallback mirrors the explicit
reduced rule set before and during hydration. An explicit product preference
may override the OS preference because users can choose it directly in
Settings.

Reduced mode preserves every final state while removing spatial transform
interpolation, layout motion, press scale, overlay movement, smooth scrolling,
spinner rotation, and skeleton pulsing. Controls may retain short color,
background, border, and opacity feedback; icon rotation/translation, progress
scaling, and shape changes commit at the instant duration. Motion is never the
only carrier of status: text, shape, icon, semantics, or live announcements
still communicate the outcome.

This policy follows W3C's recommendation to suppress nonessential
interaction-triggered motion when `prefers-reduced-motion` is active and
Apple's guidance to replace axis/depth motion with static changes or fades for
sensitive users.

## Performance and maintenance

- Prefer `transform` and `opacity`; do not animate width, height, top, left,
  box-shadow, filter, blur, or the document scroll position. Workspace Shell
  commits the rail's final width in the interaction state update, then applies
  a bounded WAAPI FLIP: the content region translates from its captured visual
  position while a fixed-width chrome layer interpolates `clip-path`. It never
  scales descendants, never retains a persistent `will-change`, cancels on a
  rapid reversal or a switch to reduced/skip policy, and releases completed or
  cancelled `Animation` references.
- Keep one moving region at a time. Parent and child must not both animate the
  same geometry unless a documented choreography requires it.
- Keep the global provider runtime-free. A runtime-enabled route uses one
  `MotionRuntimeProvider` with async `domMax`, the minimal `m` component, and
  strict mode; feature code never creates another feature loader.
- The Home release-entry route may add less than 6 KiB gzip of initial
  JavaScript against a clean `main` production build made with the same
  Node/pnpm versions. The async `domMax` feature chunk may remain below 30 KiB
  gzip. Measure the unique script URLs emitted in each route's production HTML,
  gzip the exact `.next/static/chunks` files at level 9, and compare totals;
  never pin hashed chunk names in a gate.
- CSS/WAAPI owns frequent or first-screen presence. Runtime presence and layout
  belong behind a route or interaction boundary that genuinely needs React
  exit retention, interruption, or measured geometry.
- Never wait for an animation before committing state, changing focus, or
  enabling a valid action.
- Preserve DOM semantics. Motion wrappers replace the same semantic element;
  they do not add a clickable `div` or hide content from assistive technology.
- Delete obsolete variants, recipes, stories, and docs with their last
  consumer. Do not keep aliases for speculative reuse.

Motion's own bundle guide documents why `m` plus `LazyMotion` minimizes an
opted-in runtime route. Scholens does not interpret that guidance as permission
to load `LazyMotion` globally: the persistent preference provider and CSS root
policy are independent from `MotionConfig`. Motion is MIT-licensed. Radix's
animation contract supports the CSS-first half of this architecture without
changing its accessible primitive behavior.

## Design and verification workflow

1. Name the state change and the information motion must communicate.
2. Reuse a semantic recipe or runtime variant. If none fits, document the new
   cross-product role before adding it to the foundation.
3. Add or update a deterministic Storybook state. Use the Motion toolbar to
   review `full`, `reduced`, and `system`; use Motion Lab for token and recipe
   calibration.
4. Review Light, Dark, English, Simplified Chinese, keyboard, 320 px, and the
   primary mobile widths when the changed surface supports them.
5. Verify the system preference and explicit override in a real browser. The
   dedicated Playwright smoke runs in Chromium, Firefox, and WebKit; the full
   product suite remains Chromium-owned.
6. Sync the named intent and values to the Figma Motion Foundations section.
   Code remains authoritative for numeric tokens, runtime behavior,
   accessibility, and responsive algorithms.
7. Run `pnpm tokens:check`, `pnpm design:check`, `pnpm test`,
   `pnpm test:storybook`, and the affected Playwright journeys before the full
   Web gate.

The canonical design-side reference is
[Foundations / Motion](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=1120-19).
It contains the `Scholens / Motion` variable collection plus duration, easing,
semantic choreography, and reduced-motion guidance. Numeric values originate
in `tokens/motion.json`; Figma records the agreed intent and review surface.

Primary references:

- [Motion bundle-size and LazyMotion guidance](https://motion.dev/docs/react-reduce-bundle-size)
- [MotionConfig reduced-motion behavior](https://motion.dev/docs/react-motion-config)
- [Radix animation guide](https://www.radix-ui.com/primitives/docs/guides/animation)
- [W3C Technique C39 for prefers-reduced-motion](https://www.w3.org/WAI/WCAG21/Techniques/css/C39.html)
- [Apple Human Interface Guidelines: Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- [Motion source and MIT license](https://github.com/motiondivision/motion)
