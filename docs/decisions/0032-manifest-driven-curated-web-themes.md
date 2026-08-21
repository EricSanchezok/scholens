# ADR 0032: Keep Web themes curated, manifest-driven, and geometry-safe

- Status: Accepted
- Date: 2026-08-21

## Problem

The DTCG foundation already separated Theme from Light/Dark appearance, but the
token builder, pre-hydration script, Storybook decorator, and Settings preview
still hard-coded `default`. Adding another theme would therefore require several
coordinated edits without a machine-checked theme contract. The existing Theme
layer also described only palette values, leaving it unclear whether a theme
could change layout density, touch geometry, typography, or motion.

## Decision

Scholens ships a curated set of built-in Web themes registered in one committed
manifest. Every registered theme has one self-contained DTCG bundle with the
same token paths and types as the default theme. Token generation produces the
runtime selectors and typed metadata consumed by the application, Storybook,
and the pre-hydration script.

Theme and Appearance remain independent. A theme may change palette values,
semantic color outcomes, interface font family and weights, non-pill radii,
icon stroke, and elevation recipes. It may not change spacing, content and
layout widths, breakpoints, type sizes, control or touch sizes, focus geometry,
scrollbar geometry, Reader source typography, or motion semantics. These
invariants keep the same component usable and recognizable in every theme.

Theme preferences remain browser-local through the existing localStorage and
cookie keys. The public Settings selector is rendered only when at least two
themes are registered. Unsupported or retired stored values fall back to the
manifest default before hydration.

Generated metadata also exposes the manifest default theme's canonical
Light/Dark PWA colors. Static browser-chrome metadata uses that stable default
contract rather than reaching into a theme JSON file or duplicating hex values.

Every Theme × Appearance output is checked for token parity, direct reference
resolution, required selectors, and canonical WCAG contrast pairs. Theme Lab is
the executable Storybook review surface. Figma remains the visual-intent source
and receives a matching mode only when a real curated theme is designed.

## Alternatives considered

- **Continue editing hard-coded lists.** This keeps the current implementation
  small but makes every theme addition a drift-prone cross-file procedure.
- **Allow themes to change density and layout geometry.** This multiplies the
  responsive and accessibility matrix and makes a theme behave like a second
  component system.
- **Accept user-imported or remotely configured themes.** This requires an
  untrusted token validator, versioning, isolation, asset policy, and offline
  fallback that the product does not need.
- **Add a CSS-in-JS theme runtime.** This duplicates the DTCG and generated CSS
  authority established by ADRs 0002 and 0007.

## Consequences

A new theme adds one complete DTCG bundle, one manifest entry, localized names,
Figma acceptance, and verification evidence. It does not change components,
runtime parsing, Storybook configuration, or global CSS imports. Theme authors
have broad visual-expression control while product geometry remains stable.
Adding a new downloadable font still requires an explicit reviewed font asset
registration; theme JSON never loads an arbitrary remote font.

## Validation

`pnpm tokens:check` proves generated artifacts match the manifest and DTCG
inputs. `pnpm design:check` proves theme parity, references, selectors,
contrast, adapters, and styling boundaries. Unit, Storybook, and three-browser
theme smoke tests prove preference resolution and runtime application.
