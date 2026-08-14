# Scholens Web Foundation

`web/` is the canonical Scholens frontend. It is an independent application and
does not import from the legacy `client/`. The implemented product surface
includes the authentication lifecycle at `/login`, authenticated Home at `/`,
Library at `/library`, Projects at `/projects` and `/projects/[projectId]`, and
Reader at `/reader/[documentId]`.

Canonical source ownership does not yet mean production cutover. The current
production Release and Compose path still builds and serves `client/`; see
[`deploy/production/README.md`](../deploy/production/README.md). Do not remove
the legacy application or claim that `web/` is production-deployable until a
separate reviewed cutover changes the image, proxy, health-check, rollback, and
release contracts together.

## Local commands

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm dev                 # http://127.0.0.1:7300
pnpm storybook           # http://127.0.0.1:7306, no API required
pnpm test
pnpm test:storybook
pnpm test:e2e
pnpm i18n:check          # message keys and ICU arguments stay aligned
pnpm design:check        # token parity, adapters, styling and Storybook contract
```

Authentication modes are available at `/login`, `?mode=register`,
`?mode=forgot`, `?mode=verify&token=...`, and `?mode=reset&token=...`. Review
the isolated states under `Features/Authentication/Lifecycle` in Storybook.

Both commands use fixed loopback ports and fail on a conflict. The legacy
comparison client remains available at `http://127.0.0.1:7303`.

## Boundaries

- `src/components/ui`: request-free primitives without product vocabulary.
- `src/components/feedback`: reusable async and empty-state patterns.
- `src/design-system`: DTCG sources, generated tokens, themes, and Iconoir wrapper.
- `src/lib/api`: generated OpenAPI types, transport, and normalized errors.
- `src/lib/query`: Query Client conventions.
- `src/app`: routes and provider composition only.

Run `pnpm tokens:build` after editing DTCG sources and `pnpm api:generate`
after the committed public OpenAPI snapshot changes. Generated files are
committed and checked for drift in CI.

## Engineering handbook

The rules for extending this foundation live in [`docs/`](./docs/README.md).
Read the relevant guide before adding a feature, component, token, API call, or
test:

- [`architecture.md`](./docs/architecture.md): dependency direction, feature
  slices, state ownership, and route boundaries.
- [`frontend-governance.md`](./docs/frontend-governance.md): add/change/delete
  lifecycle and Figma/Storybook acceptance contract.
- [`component-development.md`](./docs/component-development.md): component
  classification, API design, external component intake, and Storybook rules.
- [`design-tokens.md`](./docs/design-tokens.md): Figma/DTCG workflow, semantic
  styling, themes, and generated artifacts.
- [`internationalization.md`](./docs/internationalization.md): locale
  resolution, message catalogs, formatting, and Storybook workflow.
- [`authentication-foundation.md`](./docs/authentication-foundation.md): auth
  session runtime, responsive contract, forms, errors, and mock scenarios.
- [`api-development.md`](./docs/api-development.md): public OpenAPI snapshots,
  typed transport, query conventions, and coordinated schema changes.
- [`testing.md`](./docs/testing.md): unit, Storybook browser, MSW, accessibility,
  and Playwright responsibilities.
- [`new-feature-checklist.md`](./docs/new-feature-checklist.md): the required
  checklist for every new vertical slice.

Architecture exceptions require a short decision record in the repository-wide
[`docs/decisions/`](../docs/decisions/README.md); they must not be hidden inside
a feature implementation.
