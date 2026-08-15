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
design-system boundary. `LazyMotion` asynchronously loads `domMax` in strict
mode. A single `MotionProvider` owns `system`, `reduced`, and `full` preference,
pre-paint root attributes, storage/cookie persistence, system media-query
changes, and the runtime reduced-motion policy. Reduced mode retains state and
short color/opacity feedback while removing spatial, layout, smooth-scroll,
and perpetual animation.

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
Motion feature chunk adds a dependency, while strict imports and CSS-first
coverage limit its critical-path cost.

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
