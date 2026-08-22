# 0037 — Registry intake without a second UI system

Status: Accepted
Date: 2026-08-22
Owners: Web

## Problem

Scholens needs a more coherent and materially layered interface, while the Web
application already owns generated semantic tokens, Iconoir semantics, Radix
interaction primitives, motion policy, product-specific components, and a
large Storybook acceptance matrix. ReUI and React Bits provide useful source
recipes through shadcn-compatible registries, but wholesale installation would
create a second token vocabulary, icon set, primitive system, and motion
runtime. ReUI Pro source is also outside the licensed scope of this work.

## Decision

Configure ReUI and React Bits as source-intake registries, not runtime design
systems.

- ReUI intake is limited to public free examples and primitives whose source is
  available through the configured registry. We adapt composition and delete
  its raw colors, spacing, typography, icon imports, portal assumptions, and
  duplicated primitives.
- React Bits is an optional motion-recipe source. A recipe is accepted only when
  motion communicates hierarchy or state, uses the existing Scholens motion
  policy, has a static cue, honors reduced motion, and does not add decorative
  workspace backgrounds or cursor effects.
- Product components remain in their owning feature. Collection rows retain
  native list or table semantics and are not routed through a generic Item
  abstraction.
- Shared intake is allowed only for a genuinely generic primitive with multiple
  product consumers. The first such primitive is `Frame`/`FramePanel`, adapted
  from ReUI's Frame composition to Scholens semantic surfaces and concentric
  radii.
- Scholens keeps one token authority, one Iconoir wrapper, one Radix primitive
  family, and one semantic motion runtime. Registry source never overrides an
  existing shared primitive automatically.

## Alternatives considered

- **Adopt ReUI as the application component library.** Rejected because source
  availability and licensing vary, and its theme, icons, and component
  ownership would compete with established Scholens contracts.
- **Install React Bits effects globally.** Rejected because decorative
  backgrounds, cursors, and continuous motion conflict with a focused research
  workspace and its reduced-motion guarantees.
- **Copy visual recipes page by page.** Rejected because repeated surface and
  radius classes would drift and recreate the inconsistency this work is meant
  to remove.
- **Use no external references.** Rejected because public source recipes provide
  useful, inspectable composition patterns without requiring a runtime
  dependency.

## Consequences

The registries improve discovery speed without changing application ownership.
Every accepted recipe still requires source inspection, Scholens adaptation,
isolated Storybook coverage, Light/Dark and narrow review, and proportional
tests. Some visually attractive registry blocks will be deliberately rejected
when they duplicate the stack or spend attention without clarifying a task.

The Web handbook owns the current visual-language and intake rules. Future
changes that establish another token authority, icon set, primitive family, or
motion runtime require a superseding ADR.

## Validation

- `pnpm architecture:check` continues to report one permitted dependency
  direction and no cross-feature primitive ownership.
- `pnpm design:check` continues to report one generated theme contract and one
  semantic icon system.
- Every reusable intake has isolated Storybook states, including narrow content
  and Dark review.
- Registry additions are inspected with `shadcn view` before source is adapted.
