# Product identity

Scholens uses an achromatic raven portrait as its product identity. The
identity is a product-specific visual asset, not a functional interface icon
and not a second icon system.

## Canonical portrait

- The selected portrait is the single source for product lockups, browser
  chrome, launcher artwork, social previews, and the fatal startup surface.
- Compact lockups deliberately render the same portrait at 24 or 32 px rather
  than maintaining a separately drawn small-size mark.
- Do not substitute a letter, independently redraw the raven, recolor it, or
  introduce a second optical version.

Source, provenance, export rules, and generated groups are documented in
[`brand/README.md`](../brand/README.md). Generated assets are committed so a
production build does not depend on image tooling or remote generation.

## Product surfaces

`ProductMark` and `ProductLockup` in the `product-identity` feature are the
shared rendering boundary. They are used only at meaningful brand entry points:

- authentication entry;
- expanded desktop workspace navigation;
- mobile workspace navigation;
- public documentation header;
- unrecoverable application startup failure.

Ordinary loading, empty, success, and recoverable error states do not repeat the
mascot. Functional controls continue to use the semantic Iconoir wrapper.

The raster portrait keeps its authored grayscale at every size and must not
introduce raw colors into component CSS.

## Web and PWA contract

The App Router owns favicon, application, Apple touch, Open Graph, and Twitter
metadata images. `/manifest.webmanifest` publishes standard and `maskable`
launcher icons for the responsive Web application. Offline support remains an
independent runtime concern: any service worker, caching policy, or install
promotion must consume this canonical asset set rather than introduce another
icon source.

Future native shells start from the platform-neutral exports under
`brand/exports/native`. Platform-specific rounding, `.icns`, Apple asset
catalogs, and Android mipmaps are generated only when their owning shell exists.

## Change and verification contract

Edit only the selected portrait under `brand/source`, then run:

```bash
pnpm brand:build
pnpm brand:check
```

`brand:check` verifies source provenance and byte-for-byte generated output.
The root Web lane runs this check before the existing token, API, i18n, design,
test, Storybook, build, and Playwright gates.
