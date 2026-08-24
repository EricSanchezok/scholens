# Design Tokens and Figma Workflow

## Authority and flow

The token graph mirrors the Figma architecture:

```text
DTCG theme bundle primitives
  -> theme palette and expression aliases
  -> Light/Dark semantic aliases
  -> generated CSS variables and TypeScript metadata
  -> Tailwind semantic utilities
  -> components
```

Current source files:

```text
src/design-system/tokens/
├── themes/
│   ├── manifest.json
│   └── default.json
├── semantic/light.json
├── semantic/dark.json
├── contrast.json
├── dimensions.json
└── motion.json

src/design-system/adapters/
└── tailwind.json
```

Figma is used to explore and validate visual intent. After initial calibration,
the DTCG files in this repository are the numeric source of truth. Do not edit
files under `src/design-system/generated` by hand.

## Token layers

- **Theme bundles** contain their raw primitives, stable palette slots, interface
  font and weight roles, non-pill radii, icon stroke, and elevation recipes.
- **The manifest** owns the ordered theme registry and default theme. Runtime,
  Storybook, generated metadata, and Settings consume that one registry.
- **Semantic tokens** describe purpose: canvas, surface, text, border, action,
  focus, selection, feedback, annotation, and elevation.
- **Composite effects** assemble semantic colors and geometry into reusable
  elevation recipes.
- **Framework adapters** expose stable utility names; they do not own values.
- **Component styles** consume semantic tokens only.

Do not alias semantic tokens to other semantic tokens. Both Light and Dark map
directly to the theme palette so the graph remains inspectable.

Theme controls visual expression, not product geometry. Spacing, layout widths,
breakpoints, type sizes, control and touch sizes, focus and scrollbar geometry,
Reader source typography, pill/circle radii, and motion remain shared across all
themes. This keeps responsive behavior and accessibility invariant.

## Editing workflow

1. Identify whether the change is primitive, theme, semantic, or component
   level. Prefer the highest meaningful layer; do not change a primitive to fix
   one component.
2. Update the relevant DTCG source using `$type`, `$value`, and references.
3. Run `pnpm tokens:build`.
4. Run `pnpm design:check` to validate theme and appearance parity, references,
   contrast, generated selectors, adapter aliases, and forbidden styling
   shortcuts.
5. Inspect Light and Dark stories, focus, disabled, feedback, overlay, and long
   content in Storybook.
6. Run `pnpm tokens:check`, tests, and builds.
7. Commit the DTCG source and generated output together.

`tokens:check` regenerates into a temporary directory and fails if committed
outputs drift. Manual edits to generated CSS or metadata therefore fail CI.

## Using tokens in components

Use semantic Tailwind names generated from the adapter, for example
`bg-canvas`, `bg-surface`, `text-foreground`, `text-muted`, `border-line`, and
`bg-primary`, plus `text-ui`, `text-caption`, `shadow-overlay`, and
`shadow-composer`. `elevation.composer` is the mobile input-surface lift: it
uses the shared 0/6/20/-10 geometry with a 12% black Light shadow and the
existing 40% overlay in Dark. Desktop Composer surfaces retain
`elevation.raised`. If a
necessary semantic role does not exist, add and document the role instead of
writing hex, RGB, HSL, a primitive palette value, or a repeated arbitrary
recipe at the call site.

The Tailwind `@theme` adapter is appended to generated `dimensions.css`. It maps
stable color, font, font-weight, radius, type, and shadow utilities to the
active theme variables. Add or
rename an alias in `src/design-system/adapters/tailwind.json`; never recreate an
`@theme` table in global CSS. Typography aliases additionally have small stable
`@utility` registrations in `src/styles/globals.css`. Their values still come
from generated semantic variables, but keeping the registrations outside the
generated file prevents a concurrent token regeneration from changing compact
interface density in a running development server. Do not replace them with
component-local pixel sizes. `design:check` requires every typography alias to
have both its theme mapping and its stable utility registration.

`src/styles/globals.css` imports generated `dimensions.css` before
`tailwindcss`. This order is part of the build contract: Tailwind must discover
the generated `@theme inline` aliases before it emits semantic utilities such
as `bg-primary`, `bg-elevated`, `text-foreground`, and `border-line`.
`design:check` rejects an inverted order because it can leave raw token
variables present while silently removing the component utility rules that
consume them.

`font.reading-serif` is a deliberately narrow content role for English source
text in the AI reflow academic reading surface. It is not a product-interface
font and must not replace Geist in navigation, controls, metadata, or translated
text. Reader translations continue to use the product sans stack so source and
translation remain distinguishable without introducing decorative chrome.

Interactive descendants inherit the state of their shared control. In
particular, an icon inside a disabled button resolves to the shared disabled
icon role even when its enabled state is inverse. Composite controls may
suppress a native child's outline only when the containing control exposes the
shared focus-visible surface. Mark that child with
`data-focus-delegate="surface"` and its owner with `data-focus-surface`; use
`data-focus-delegate="self"` when the native element remains the complete
interaction surface. These attributes keep composite controls from drawing a
second rectangle around an inner input.

Ordinary interactive elements consume `focusSurfaceVariants({ intent })`.
Normal Light and Dark focus feedback uses `color.focus.surface`,
`color.focus.foreground`, `color.focus.secondary`, `color.focus.icon`, and
`color.focus.scrollbar`; it does not alter the structural border or introduce a
ring, outline, or zero-offset perimeter shadow. Primary, danger, status, and an
explicitly approved bounded card may add the existing offset
`elevation.raised` recipe through those shared intents. The
`keyboardFocusRing`, `color.focus.ring`, and
`color.border.focus` contracts are retired and must not be restored or aliased.
Global CSS owns the shared recipes, delegation, and forced-colors fallback
only; forced colors use `focus.width` (`--focus-width`) with system `Highlight`
rather than a product focus-color token. Selection controls explicitly map
checked state to system colors, while Reader color swatches preserve only their
inner document color and keep focus on the outer system-owned button.

Disabled prominence is also semantic. If a disabled primary action disappears
into a canvas in one appearance, adjust `color.action.disabled-*` for that
appearance and review every disabled-button story. Do not patch the individual
button or feature call site.

Allowed raw-color exceptions are limited to source images, PDF content, and
third-party brand marks that must preserve their identity. The surrounding UI
still uses semantic tokens.

Scrollbars are a shared shell primitive, not a page-local decoration. Both
axes use `dimension.scrollbar.box` for a quiet 4 px interaction gutter and
`dimension.scrollbar.thumb` for the 2 px thumb. Native document, element, and
Radix `ScrollArea` thumbs remain transparent at rest, appear only on the
scroller receiving input, wait for 500 ms of inactivity, and then fade over the
deliberate motion duration. The active thumb uses a quiet translucent form of
`color.scrollbar.thumb`; hover resolves through `color.scrollbar.thumb-hover`;
WebKit scrollbar pseudo-elements own the exact geometry and motion in Chromium
and Safari, while a Firefox-only standards-based fallback uses
`scrollbar-width` and `scrollbar-color` without overriding those pixel
dimensions or transitions. Radix tracks expose the same
`data-scrollbar-track` and `data-scrollbar-thumb` contract and retain their
scrolling state long enough for the shared fade to finish before unmounting.
Forced-colors mode keeps persistent system `Canvas` and `CanvasText`
scrollbars. Stable gutters belong
only to persistent scrolling regions, and horizontal scrolling is opt-in for
content such as code blocks, tables, or a ScrollArea with an explicit
horizontal bar; ordinary layouts must wrap or clip rather than widen the page.

Reader annotation colors are document-content roles rather than status roles.
Define the curated hue set under `document-highlight`, expose every hue through
the semantic graph in both appearances, and apply opacity at the PDF overlay.
Do not reuse success, warning, info, selection, or search backgrounds for
persisted annotations; those roles carry different meaning and are usually too
subtle to work as annotation swatches.

Icon semantics follow the same indirection rule as colors. Product components
consume the named registry in `src/design-system/icons/semantic-icons.ts`, not
raw Iconoir names. The registry is one-to-one: one product meaning resolves to
one glyph, and one glyph cannot be assigned to competing meanings. The
registry test and `design:check` make this contract executable.

PDF overlays also keep separate semantic roles by behavior. Browser text
selection uses `color.document-selection.bg`; document search uses
`color.document-search.match` for every result and
`color.document-search.current` for the active result. Search colors remain
translucent because they sit above the rendered PDF canvas and must not hide
the original glyphs.

## Runtime contract

```html
<html data-theme="default" data-color-scheme="light"></html>
```

- Theme preference key: `scholens-theme`.
- Appearance preference key: `scholens-color-scheme`.
- Appearance preference values: `system`, `light`, or `dark`.
- Preferences are stored in localStorage and cookies.
- The inline initialization script resolves appearance before paint.
- The React provider exposes only explicit initial props or `default`/`system`
  during the server and first hydration snapshot, then adopts persisted
  preferences after hydration. The inline script remains responsible for the
  root element before paint, so this deterministic boundary does not add a
  flash.
- Unsupported or retired theme values fall back to the manifest default.
- Settings shows Theme choices only when the manifest contains two or more
  themes.
- Generated metadata exposes `pwaColors.light` and `pwaColors.dark` for the
  manifest default theme's canvas, primary/secondary foreground, and border.
  PWA browser chrome consumes this contract instead of theme files or repeated
  hex values.

Theme and Appearance remain independent. Adding Ocean must not create combined
`Ocean Light` and `Ocean Dark` mode names.

Motion is an independent generated foundation. `motion.json` owns the shared
duration, easing, and spring parameter scale. Because DTCG has no portable
compound spring type, stiffness, damping, and mass use standard numeric tokens;
`tokens:build` assembles those runtime-only values into
`generated/motion-metadata.ts` and excludes them from generated CSS. The same
build emits `generated/motion.css` for CSS recipes. Do not copy a duration,
Bézier curve, or spring into a feature. The complete authoring, preference, and
reduced-motion contract is in [Motion system](./motion.md).

## Adding a theme

1. Add one self-contained `tokens/themes/<theme>.json` with exactly the same
   paths and DTCG types as Default, then register its kebab-case ID in
   `themes/manifest.json`.
2. Add the English and Simplified Chinese Settings name. Runtime metadata,
   generated CSS, Storybook controls, and the Settings picker update
   automatically.
3. Run token generation and checks, then review Theme Lab plus representative
   feature compositions in Light and Dark.
4. Sync the matching Figma Theme mode and verify its aliases.

Do not add a new theme until all semantic roles resolve in both appearances,
the contrast contract passes, and every required font asset is explicitly
registered. Theme JSON must never load a remote font or runtime stylesheet.

## Figma synchronization

For a design-led change:

1. Explore the palette or semantic mapping in Figma Theme Lab.
2. Agree on token names and behavior, not frame coordinates.
3. Apply final numeric values to DTCG and generate code artifacts.
4. Update Figma from the agreed token data rather than independently tweaking
   copies of screens.
5. Validate canonical Figma frames against Storybook/implementation.

Motion uses the same workflow through the canonical
[Foundations / Motion](https://www.figma.com/design/2T5BuTPMIrM2jsVhgIVYIX/Scholens-%E2%80%94-Product-Design?node-id=1120-19)
section and the `Scholens / Motion` variable collection. The generated code
tokens remain authoritative for runtime values.

Code may use a robust Radix or Scholens component instead of copying a Figma
layer tree exactly. Layout hierarchy, density, state meaning, and visual intent
must remain consistent.
