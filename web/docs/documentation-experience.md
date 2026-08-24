# Documentation experience

`/docs` is the public MCP onboarding surface for people connecting external
research agents to Scholens. It is a Read-mode page inside the established
Scholens visual system: semantic tokens, Geist typography, restrained surfaces,
and the shared Iconoir wrapper. It does not require an authenticated session or
introduce a separate documentation application.

No canonical Figma frame exists for this route. The user-approved content plan,
the incumbent Web implementation, and the responsive acceptance states below
are its design authority.

The sticky header uses the shared compact Scholens raven lockup. It remains a
single home link followed by the localized Docs suffix; the brand image does
not add another focus target or compete with documentation wayfinding.

## Entry points and navigation

Authenticated users reach the guide from the Workspace account menu or the
Access Keys panel. Anonymous users reach it from the authentication footer or a
direct URL. The account and authentication entries open a new tab so current
work is retained; the Access Keys link targets `/docs#mcp-setup`.

The route supports a shareable `?client=` selection for `codex`,
`claude-desktop`, `cursor`, and `generic`; missing and invalid values resolve to
Codex. Desktop uses a sticky table of contents beside a readable content
column. Narrow layouts replace it with a compact native disclosure. Every
stable section ID is shared by the visible page and machine documentation.

## Content contract

The typed documentation-content model owns MCP endpoint derivation, the 63-tool
catalog total, six reviewed capability groups, permissions, resources,
templates, client examples, local connector configuration, file-size limit,
release revision state, and repository-binding sample. Localized page prose
remains in the English and Simplified Chinese message catalogs. The visible
page, `/docs.md`, and `/llms.txt` consume the same factual model rather than
copying those values.

The remote endpoint is the origin of `NEXT_PUBLIC_API_URL` plus `/mcp`.
Machine-documentation links use the canonical application origin rather than the
incoming request origin, because the Next.js standalone server receives its internal
container address behind the production proxy. Codex uses
`bearer_token_env_var`, Cursor uses environment interpolation in the
Authorization header, Claude Desktop uses the official local `uvx` bridge, and
the generic example states the Streamable HTTP and Bearer requirements without
inventing a client-specific schema.

Production builds supply a lowercase 40-character `NEXT_PUBLIC_RELEASE_SHA`.
The generated `uvx --from` URL pins the connector Git source to that exact
revision, keeping the downloaded bridge aligned with the deployed Web/API
release. Local development and Storybook use the explicit, visibly labeled
mutable `@main` fallback; they never present it as release-pinned.

The guide states the product boundary directly: Scholens operates on stored
research knowledge and known-source ingestion. Internet literature discovery
and generation of new research outputs are absent. Destructive or externally
visible operations retain the state-bound two-call confirmation contract.

## Machine-readable routes

- `GET /docs.md` returns the complete English guide as
  `text/markdown; charset=utf-8`.
- `GET /llms.txt` returns the concise authority and endpoint index as
  `text/plain; charset=utf-8`.
- `GET /docs` emits a `Link` response header identifying `/docs.md` as the
  alternate Markdown representation.

These routes are public and cacheable but contain placeholders rather than real
Access Keys. No backend API or OpenAPI DTO is added.

`pnpm docs:check` also reads `server/contracts/mcp-v1.json` directly and fails
when its published tool count differs from `MCP_TOOL_COUNT`, the six page
capability-group totals, or both. The check is build-time governance only; Web
runtime code does not import Server packages or the contract snapshot.

## Acceptance

Storybook covers the English default, Cursor selection, Simplified Chinese Dark
mode, and the 320px minimum viewport. Interaction coverage verifies copy
feedback, shareable client selection, stable links, and the Access Keys entry.
Playwright covers anonymous page access, response headers, machine routes,
accessibility, and horizontal containment. Review the page at 1440px, 390x844,
430x932, and 320x568 in Light and Dark before release.
