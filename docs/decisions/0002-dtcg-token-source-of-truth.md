# ADR 0002: Keep design-token values in repository DTCG files

- Status: Accepted
- Date: 2026-08-02

## Problem

Scholens needs multiple themes and Light/Dark appearances without visual drift
between Figma, application components, Tailwind utilities, and Storybook.
Allowing each surface to own color values would create several competing
sources of truth.

## Decision

After the initial Figma calibration, DTCG JSON under
`src/design-system/tokens/` is the numeric source of truth.

- Style Dictionary generates CSS variables and TypeScript metadata.
- Components consume semantic variables, never primitive palette values.
- Raw brand colors are not written inside components.
- Generated files are not edited by hand.
- Theme and Appearance remain independent dimensions.
- Figma continues to express visual intent and receives synchronized values
  through an explicit token update workflow.

## Alternatives considered

- **Let Figma remain the numeric runtime source.** Application builds would
  depend on an external mutable file and repository review could not prove the
  exact values being shipped.
- **Maintain theme values directly in CSS or components.** This would create
  competing authorities and make Light/Dark, themes, and Storybook drift from
  one another.

## Consequences

Theme changes propagate predictably to the app and Storybook. Token updates
require generation and drift checks, but reviews can distinguish deliberate
design changes from accidental local styling.
