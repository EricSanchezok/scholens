# Product identity

Scholens uses a monochrome raven as its product identity. The identity is a
product-specific visual asset, not a functional interface icon and not a
second icon system.

## Optical versions

- The high-detail portrait is used at 64 px and above, including launcher
  artwork, social previews, and the fatal startup surface.
- The micro mark preserves the raven's profile, beak, and monocle at 16–48 px.
  It is used for browser chrome and compact product lockups.
- The two versions represent the same character. Do not substitute a letter,
  recolor the raven, or compress the portrait into a size where its defining
  details disappear.

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

The compact SVG is rendered as a CSS mask so it inherits the surrounding
semantic foreground color in Light and Dark modes. The raster portrait keeps
its authored grayscale and must not introduce raw colors into component CSS.

## Web and PWA contract

The App Router owns favicon, application, Apple touch, Open Graph, and Twitter
metadata images. `/manifest.webmanifest` publishes `any`, `maskable`, and
`monochrome` icons for the responsive Web application. Offline support remains
an independent runtime concern: any service worker, caching policy, or install
promotion must consume this canonical asset set rather than introduce another
icon source.

Future native shells start from the platform-neutral exports under
`brand/exports/native`. Platform-specific rounding, `.icns`, Apple asset
catalogs, and Android mipmaps are generated only when their owning shell exists.

## Change and verification contract

Edit only the two files under `brand/source`, then run:

```bash
pnpm brand:build
pnpm brand:check
```

`brand:check` verifies source provenance and byte-for-byte generated output.
The root Web lane runs this check before the existing token, API, i18n, design,
test, Storybook, build, and Playwright gates.
