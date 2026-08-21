# Scholens product identity assets

Scholens uses one raven character at two optical-detail levels:

- `source/scholens-raven-master.png` is the selected high-detail portrait for
  surfaces at 64 px and above.
- `source/scholens-raven-micro.svg` preserves the head, beak, and monocle as a
  crisp silhouette for browser chrome and compact product marks.

The portrait was generated with OpenAI ImageGen and selected on 2026-08-21.
Its SHA-256 is
`c0147099ca28a03f63e922b81177adb3e50667ca4da9370dc0ff3ed2558ef5de`.
The repository does not claim a more specific generator version that was not
recorded at selection time.

## Rules

- Keep the identity achromatic. Product UI around the asset uses existing
  semantic color tokens; the raster artwork may retain its authored grayscale.
- Do not shrink the portrait below 64 px. Use the micro mark instead.
- Do not replace the raven with an `S`, independently redraw its expression,
  remove the monocle, or add color accents.
- Do not pre-round launcher artwork. Operating systems own the final mask.
- Keep important maskable content inside the central safe circle.
- Do not edit generated outputs directly. Run `pnpm brand:build` after changing
  either source and commit the sources and outputs together.

## Generated groups

- App Router metadata images live in `src/app`.
- Browser and PWA runtime assets live in `public/brand`.
- `exports/native` is a platform-neutral handoff. Native shells should generate
  their own `.icns`, asset catalogs, and Android mipmaps when those shells
  actually exist.
