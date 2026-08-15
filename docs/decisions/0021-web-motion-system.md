# 0021 — Semantic Web motion system

Status: Accepted
Date: 2026-08-16
Owners: Scholens

## Problem

The replacement frontend had complete static states but no shared motion
language. Individual call sites could add unrelated Tailwind transitions,
keyframes, timings, or animation libraries. That would make product behavior
noisy, make reduced-motion support inconsistent, increase bundle cost, and
leave Figma, Storybook, and runtime code without one reviewable contract.

Scholens needs both simple primitive feedback and measured React layout
continuity. CSS alone cannot retain exiting React content or interpolate a
changing list/panel layout. A JavaScript runtime everywhere would duplicate
the state and mount lifecycle that Radix already exposes and would make basic
controls unnecessarily expensive.

## Decision

Scholens adopts a two-layer semantic motion system:

1. generated DTCG-style duration and easing tokens plus shared CSS recipes own
   controls, Radix overlays, feedback, progress, and loading presentation;
2. Motion for React is the only animation runtime and is reserved for bounded
   mount/unmount choreography and measured layout continuity.

Product code imports the minimal `m` API and shared variants through the
design-system boundary. The application-wide `MotionProvider` owns `system`,
`reduced`, and `full` preference, pre-paint root attributes, storage/cookie
persistence, and system media-query changes without importing Motion for
React. Runtime-enabled routes opt in through `MotionRuntimeProvider`, which
owns `MotionConfig` and asynchronously loads `domMax` through strict
`LazyMotion`. Reduced mode retains state and short color/opacity feedback while
removing spatial, layout, smooth-scroll, and perpetual animation.

Home, Conversation, Settings, Authentication, and the Workspace Shell use CSS
recipes for presence and feedback. Library, Projects, Project Detail, and
Reader are route-scoped runtime consumers because their bounded list or panel
geometry needs retained exit state, interruption, or layout measurement. This
split keeps `AnimatePresence` and the Motion component core out of the Home
initial graph while preserving one semantic token and reduced-motion policy.

Preference storage is best-effort rather than a rendering dependency. When
storage is unavailable, pre-paint resolution continues through the cookie and
OS media query; `system` remains delegated to the runtime's user preference so
hydration cannot briefly opt a reduced-motion user into full motion.

The generated checker rejects direct runtime imports, raw animation utilities,
arbitrary timing, and page-local keyframes outside the foundation. Storybook
provides a global motion axis and Motion Lab. A focused smoke suite validates
pre-hydration preference and CSS/runtime policy in Chromium, Firefox, and
WebKit; the rest of the product E2E suite remains Chromium-only.

There are no full-page route transitions, scroll-triggered decoration,
parallax, animated blur, or character-by-character streaming effects. Figma
owns motion intent and acceptance annotations; repository tokens and code own
numeric values, reduced behavior, performance, accessibility, and APIs.

The release-entry budget is an initial JavaScript increase below 6 KiB gzip
against `main`; the asynchronously requested `domMax` chunk remains below
30 KiB gzip. Both builds use the same production toolchain. Route totals are
the sum of unique script URLs in production HTML, compressed from the exact
`.next/static/chunks` files with gzip level 9. Hashed filenames are evidence,
not a durable gate contract.

The 2026-08-16 controlled Home benchmark added one layer at a time to the same
strict CSS-first build. The CSS-first branch measured 725 B above `main`.
Adding global `MotionConfig` added 279 B; `LazyMotion` added 12,341 B; one raw
`m.div` added 4,855 B; `AnimatePresence` added 1,987 B; and the Scholens
semantic wrapper/barrel added 685 B. The reconstructed global-runtime total was
20,872 B above `main`. This evidence is why the runtime boundary is route-local
rather than global.

The final route-owned measurement was:

| Production route     | `main` gzip | Candidate gzip | Delta     | Motion ownership                         |
| -------------------- | ----------- | -------------- | --------- | ---------------------------------------- |
| Home `/`             | 458,460 B   | 459,185 B      | +725 B    | CSS-first; no Motion React initial chunk |
| Login `/login`       | 322,580 B   | 323,165 B      | +585 B    | CSS-first; no Motion React initial chunk |
| Library `/library`   | 469,216 B   | 489,837 B      | +20,621 B | route-local runtime                      |
| Projects `/projects` | 465,246 B   | 485,742 B      | +20,496 B | route-local runtime                      |
| Reader `/reader/:id` | 569,321 B   | 590,004 B      | +20,683 B | route-local runtime                      |

The two shared initial runtime chunks total 19,581 B gzip on opted-in routes;
the remaining 915–1,102 B is route integration and feature wrapper code. The
async `domMax` chunk is 86,956 B raw and 28,067 B gzip and is absent from route
HTML script lists. Measurements used Node 22.23.2, pnpm 10.11.0, Next production
builds, and Node zlib level 9.

## Alternatives considered

- CSS only. Rejected because React exit lifecycles and measured panel/list
  reflow would require custom bookkeeping and fragile manual geometry.
- Motion for every animation. Rejected because native CSS and Radix
  `data-state` already provide smaller and clearer primitive enter/exit
  behavior.
- GSAP. Rejected because its imperative timeline strength is unnecessary for
  this product UI and would introduce a second state model for routine React
  composition.
- React Spring. Rejected because Scholens needs declarative presence and layout
  primitives more than per-call-site physics configuration; unconstrained
  spring tuning would also weaken a shared tempo.
- AutoAnimate. Rejected because automatic DOM observation offers too little
  semantic control over which product changes animate and how reduced motion
  degrades.
- Web Animations API wrappers maintained in-house. Rejected because layout
  measurement, exit presence, interruption, and cross-browser cleanup would
  become an internal animation framework with a larger maintenance burden.
- No application preference beyond the OS media query. Rejected because users
  need a discoverable persistent choice and designers/developers need explicit
  full/reduced modes for review.

## Consequences

Motion is intentionally less flexible at feature call sites. New timings,
easings, springs, or recipes require a system-level reason and documentation.
Shared primitives gain consistent feedback and overlays; product features can
compose a small vocabulary without copying configuration. The asynchronous
Motion feature chunk adds a dependency only after entering a runtime-enabled
route, while strict imports and CSS-first coverage keep it off the Home
critical path. Runtime routes carry a deliberate initial core cost; the Home
budget is protected by a static design-system check and repeated production
bundle measurement.

Every relevant feature now has reduced-motion acceptance. CI provisions three
Playwright engines for the focused policy smoke, increasing browser-install
time but not tripling the full E2E suite. Figma must carry the same named
foundation and intent mapping, while token drift is resolved in repository
source and regenerated rather than tuned independently in frames.

## Validation

`tokens:check` verifies generated CSS and TypeScript metadata. `design:check`
enforces the import and authoring boundary. Unit tests cover preference parsing,
system changes, persistence, and root policy. Storybook interaction tests cover
Motion Lab and Settings preference changes. The motion Playwright smoke proves
pre-hydration `system` reduction and explicit `full` override in Chromium,
Firefox, and WebKit. The complete Web gate verifies existing feature journeys,
builds, accessibility, localization, and documentation.
