# DeepSeek Harness development-governance audit — 2026-08-14

## Scope and evidence

This audit compares Scholens with the local DeepSeek Harness (DSH) repository
as a development-governance reference. It reviewed DSH's `AGENTS.md`,
`CONTRIBUTING.md`, development and testing guides, package guides, Agent Note
lifecycle, workspace manifest, root gate graph, Git hooks, and CI/release
workflows. It reviewed Scholens' mandatory entry point, development and product
guides, Web handbook, Server and Jobs configuration, shared Python packages,
hooks, CI, GitHub `main` ruleset, and production deployment package.

The objective is not to make Scholens look structurally like DSH. DSH is a
public TypeScript plugin framework with many publishable packages and platform
targets; Scholens is a mixed-language product with independently deployable
Server and Jobs services, a canonical Web application, a legacy comparison
client, and two private shared Python packages.

## Scholens baseline

Scholens already has strong governance in several areas:

- `AGENTS.md` is a mandatory navigation and safety entry point;
- the pre-release reset-first policy avoids disposable compatibility layers and
  protects independent ownership of the `auth` schema;
- Web has unusually complete architecture, token, i18n, Storybook, accessibility,
  generated-API, and feature-lifecycle checks;
- fixed loopback ports, explicit setup, and no-install/no-migrate daily startup
  are documented;
- Server and Jobs have separate locks and deployable runtime ownership;
- data ownership, backend capabilities, deployment safety, and rollback are
  written down and partly machine checked.

The material problem is not an absence of rules. It is that repository-wide
workflow, shared-package obligations, decision storage, and CI requirements are
less executable and less centralized than the Web-specific handbook.

## Adopt

| DSH practice                                                           | Scholens application                                                                                                                                  |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| One mandatory entry point that routes contributors to canonical owners | Keep `AGENTS.md` concise and use `CONTRIBUTING.md`, service guides, architecture docs, and feature docs as the detailed owners.                       |
| One executable gate graph shared by local work and CI                  | Provide `scripts/run-gates.sh` targets for each deployable surface, shared packages, docs, deployment, and the complete repository.                   |
| Fast local hooks; exhaustive suites in CI                              | Hooks check staged cleanliness and cheap contracts. Focused tests run during development; CI and the explicit `all` target own the complete matrix.   |
| Machine-check package metadata and dependency direction                | Validate shared-package names, versions, Python floor, `src/` layout, README, tests, typing marker, consumers, and local `uv` sources.                |
| Test a package directly rather than only through a consumer            | Give each shared Python package its own Ruff, mypy, and pytest gate and a dedicated CI lane.                                                          |
| One canonical home per fact                                            | Keep current behavior in architecture, feature, service, and package docs; keep rationale in ADRs and ordinary verification history in pull requests. |
| Separate source verification from artifact/release verification        | Keep ordinary gates side-effect free; treat Docker, Compose, migrations, packed artifacts, and production activation as explicit deployment checks.   |

## Adapt

| DSH practice                                                       | Why Scholens uses a narrower form                                                                                                                                                                                                                     |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent Notes for every non-trivial change                           | Scholens uses repository-wide ADRs only for consequential decisions, pull requests for ordinary change rationale and evidence, and postmortems for incidents or repeated systemic regressions. A second note lifecycle would duplicate these records. |
| One pnpm workspace and root dependency graph                       | Server and Jobs remain independent `uv` projects with independent lockfiles. Shared Python packages receive a small development project and contract checker instead of forcing all services into one lock.                                           |
| Per-file 100% source coverage                                      | Scholens requires behavior-complete tests for permissions, state transitions, DTOs, shared pure logic, and UI interaction states. It does not introduce a repository-wide percentage that would reward low-value assertions.                          |
| Keyless assembled-application snapshots for every visible behavior | Storybook browser states and Playwright remain the Web assembly evidence. Conversation transcript snapshots are a future option only if they test a real deterministic assembly rather than duplicating reducer fixtures.                             |
| DSH pre-release freedom to break formats                           | Scholens already applies the same principle specifically to the public product API and `scholens` schema while preserving independent `auth` ownership and explicit deployment safety.                                                                |

## Defer

The following practices are valuable but do not block the current integration
into `main`:

- built-wheel installation smoke tests for the two shared Python packages;
- AST-enforced import boundaries beyond the initial workspace contract checks;
- repository-wide unused-code, duplication, dependency-license, and third-party
  notice automation;
- dependency vulnerability automation with an owned triage and update policy;
- a deterministic assembled conversation-output snapshot harness;
- hosted visual-diff baselines in addition to Storybook browser tests;
- the canonical Web production image, edge routing, smoke checks, source maps,
  Compose activation, and rollback cutover.

Each deferred item needs an owner and acceptance criteria before it becomes a
required gate. Adding a command that nobody can interpret or maintain would not
improve governance.

## Reject

The following DSH-specific choices should not be copied into Scholens:

- the rule that every capability is a Cordis plugin and every package peers on
  the same plugin framework;
- DSH's Host/Client TypeScript compiler faces and package invariant model;
- converting Server and Jobs into a single package-manager workspace or one
  Python lockfile;
- requiring bilingual counterparts for every engineering document;
- adopting DSH's vendored-source, public npm-family release, Windows/Wine, and
  multi-Node matrix without matching product consumers;
- enforcing 100% per-file coverage as a universal Scholens quality measure.

These choices solve DSH's distribution and ecosystem constraints, not
Scholens' current product risks.

## Findings requiring remediation before the main merge

| Finding at audit time                                                                                                                                      | Risk                                                                                                  | Required correction                                                                                                                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Decision records lived under `web/docs/decisions` even when they governed Server, Jobs, API, data, and local ports.                                        | Repository-wide decisions appeared frontend-owned and links could drift.                              | Move the complete ADR history to `docs/decisions`, normalize the required Problem/Decision/Alternatives/Consequences format, and repair every reference. |
| There was no repository contributor workflow or PR template.                                                                                               | Branch, commit, evidence, documentation, and release-impact expectations depended on chat history.    | Add `CONTRIBUTING.md` and a machine-visible pull-request checklist.                                                                                      |
| Shared packages had no common intake contract or direct CI lane.                                                                                           | Both services could pass while a package's own public contract, typing, or packaging drifted.         | Standardize `src/`, README, typing marker, direct tests, development dependencies, and workspace validation.                                             |
| Root hooks used Black/isort for only part of Server while CI used Ruff and also covered Jobs.                                                              | Local automatic rewrites disagreed with authoritative CI and ignored package boundaries.              | Replace obsolete hooks with cheap Ruff and repository contract checks; leave full tests to explicit gates and CI.                                        |
| Service docs omitted parts of the actual CI commands.                                                                                                      | A contributor could follow the README and still fail Ruff format or full mypy checks.                 | Make the root runner canonical and keep exact service-local equivalents in the owning README.                                                            |
| CI commands were duplicated directly inside workflow YAML and documentation.                                                                               | A newly added surface or check could be green but not required, or documented commands could diverge. | Route CI through the same root gate targets and add one aggregate `all checks passed` result.                                                            |
| GitHub ruleset `main-protection` (ID `20185192`) required `client`, `server`, `jobs`, and `deployment-contract`, but not canonical `web`.                  | A pull request could satisfy branch protection while the product frontend failed or never ran.        | Require the aggregate result after its first successful run so every constituent, including Web and shared packages, is transitively required.           |
| `web/README.md` still said Library, Projects, and Reader were unimplemented.                                                                               | The documented product surface contradicted the branch being reviewed.                                | Describe the implemented routes and distinguish source ownership from production cutover.                                                                |
| Release and deployment still build `client/Dockerfile` and activate `SCHOLENS_CLIENT_IMAGE`; canonical `web/` has no production image or Compose contract. | Merging the canonical frontend source could be mistaken for production readiness.                     | State explicitly that PR #12 is a source integration only, do not run Release for it, and schedule Web production cutover as a separate reviewed change. |

## Delivery and residual debt

The remediation is intentionally split into recoverable changes: documentation
and decision ownership; shared-package contracts and tests; then root gates,
hooks, CI aggregation, and branch protection. The complete repository gate must
pass before PR #12 is squash-merged into `main`.

That merge does not create a tag, image, migration, or deployment. Production
continues to serve legacy `client/` until the deferred cutover has its own
architecture decision, implementation, deployment-contract tests, and rollback
evidence.
