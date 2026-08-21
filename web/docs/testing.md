# Testing Strategy

## Test by responsibility

| Layer                                      | Tool                            | Purpose                                                                 |
| ------------------------------------------ | ------------------------------- | ----------------------------------------------------------------------- |
| Pure utilities and focused component logic | Vitest + Testing Library        | Fast deterministic behavior                                             |
| Component states and interactions          | Storybook + Vitest Browser Mode | Real Chromium, props, themes, keyboard, axe                             |
| Network-driven component behavior          | Storybook + MSW                 | Success, slow, empty, errors, offline, 401                              |
| Route/application contract                 | Playwright                      | Provider integration, navigation, critical flows, browser accessibility |
| Backend schema boundary                    | Pytest                          | Public OpenAPI snapshot and server configuration                        |

Prefer the lowest layer that catches the regression. Do not duplicate every
component assertion in Playwright.

## Required commands

```bash
pnpm tokens:check
pnpm api:check
pnpm i18n:check
pnpm architecture:check
pnpm design:check
pnpm docs:check
pnpm lint
pnpm format:check
pnpm typecheck
pnpm test
pnpm test:storybook
pnpm build-storybook
pnpm build
pnpm test:e2e
```

CI runs these in Node.js 22 with a frozen pnpm lockfile.

Playwright starts the production server from the build created by the preceding
`pnpm build` step. When running the browser lane on its own, build first; this
keeps route and chunk behavior aligned with the release artifact. The runner
never reuses a process already listening on port 7300: a conflict fails clearly
instead of silently testing another checkout or build.

## Storybook coverage

Use global toolbar controls instead of duplicating entire story files:

- Theme: every manifest-registered curated theme. Theme Lab renders the complete
  Theme × Appearance matrix and verifies that its computed variables resolve.
- Appearance: Light and Dark.
- Locale: English and Simplified Chinese. This toolbar loads the real message
  dictionary through the application provider.
- Viewport: Desktop (1440), Tablet (768), Narrow panel (480), Mobile (390), and
  Small Mobile (320). Authentication surfaces require 320, 390, 768, and 1440.
- Network: Instant, Slow, Offline.
- Data: Populated, Empty, Error.
- Motion: System, Reduced, Full. Motion Lab is the executable token, recipe,
  layout, and overlay calibration surface.

Each interactive component or product pattern covers relevant states, long
content, narrow width, keyboard interaction, and accessibility. `play`
functions assert outcomes rather than waiting arbitrary durations.

Storybook is the executable state inventory; Figma remains the visual intent
and acceptance inventory. During feature delivery, map canonical Figma states
to story IDs. A visual change is reviewed in both appearances before its
baseline is accepted. Hosted screenshot regression may be added only with an
owned service token and baseline-review policy; it does not replace semantic,
interaction, axe, or Figma review.

The Storybook Vitest browser runs with the OS reduced-motion media feature and
Motion's test-only `skipAnimations` configuration so ordinary interaction and
axe assertions observe settled UI instead of an animation's first frame. The
normal Storybook dev/build output does not skip runtime animation. Stories that
validate CSS motion set the Motion toolbar to explicit `full` or `reduced` and
assert the corresponding recipe directly; runtime interpolation is covered by
the real-browser motion smoke.

## MSW rules

- Stories and component tests never call a live API.
- Handlers model the public contract and return deterministic fixtures.
- Keep generic transport scenarios in `.storybook/msw` and feature-specific
  domain handlers beside the feature.
- Cover success, delay, empty, business error, server error, offline, and 401
  where the UI reacts differently.
- An unhandled request is a test design smell; explicitly add or intentionally
  document it rather than relying on a developer backend.

## Accessibility

Automated axe checks are a gate, not a complete audit. Also verify:

- Logical Tab and Shift+Tab order.
- Visible focus and Escape behavior.
- Dialog focus trapping and return focus.
- Accessible names for icon-only controls.
- Labels, descriptions, errors, and `aria-invalid` for forms.
- Status announcements for asynchronous changes when needed.
- Text zoom, narrow containers, long translations, and reduced motion.
- Contrast in both appearances.
- No horizontal scrolling at the 320px minimum width.
- Virtual-keyboard resilience on a physical or emulated mobile browser: the
  active field, its error, and submit action remain reachable by scrolling.
- Form usability at 200% browser text zoom in both supported locales.

Serious and critical axe violations fail Storybook tests. Critical product
flows receive a Playwright keyboard pass before release.

## Playwright scope

Use Playwright for a small set of high-value browser journeys, not exhaustive
component permutations. Tests should use stable roles and accessible names,
avoid implementation selectors, and create their own state. Network responses
must be deterministic unless a test is explicitly marked as an integration
test with the backend.

The full product suite runs in Chromium. `motion-smoke.spec.ts` additionally
runs in Firefox and WebKit, proving that the inline pre-hydration preference,
system media query, explicit override, Radix CSS recipe, and a representative
layout animation behave consistently in all three engines. CI therefore
installs `chromium firefox webkit`; do not expand the entire product suite to
three engines without evidence that its additional runtime catches a distinct
class of regressions.

Reduced-motion tests set the media query before navigation and assert root
policy plus the user-visible or computed animation outcome. They must not only
mock a React hook after hydration. Full-mode tests also exercise an explicit
preference while the OS requests reduction so precedence remains intentional.
The three-engine motion smoke also exercises the inverse precedence: explicit
`reduced` with an OS `no-preference` policy, asserting that conversation
auto-follow performs one direct write to the latest target rather than a
smooth requestAnimationFrame sequence.

`theme-smoke.spec.ts` is the corresponding three-engine foundation check for
pre-hydration system appearance, retired-preference fallback, and resolved
theme variables. Do not expand the complete product suite to every browser or
duplicate every story for each theme.

The Theme provider also has an SSR-to-hydration unit regression with a
test-only second-theme registry. It must prove that a persisted non-default
theme is adopted after hydration without a recoverable hydration error; do not
add a fake production theme merely to exercise this boundary.

Motion bundle acceptance uses production output rather than development or
Storybook chunks. Build clean `main` and the candidate with the same Node 22
and pnpm 10.11.0 toolchain, request each route from `next start`, deduplicate
its HTML script URLs, and gzip the corresponding `.next/static/chunks` files at
level 9. Home's candidate-minus-main initial total must stay below 6 KiB; the
route-scoped async `domMax` chunk must stay below 30 KiB. Report exact bytes and
route ownership in the PR, but do not make a permanent check depend on hashed
chunk filenames.

## Flake policy

- Never fix a race by adding an unconditional sleep.
- Wait for user-visible state or a specific network event.
- A flaky test is quarantined only with an owner and removal issue; it is not
  silently skipped.
- Browser console errors, unhandled requests, and React warnings are treated as
  defects.
