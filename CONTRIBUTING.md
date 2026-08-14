# Contributing to Scholens

Scholens is a pre-release product developed as a mixed TypeScript and Python
repository. Contributions should leave one coherent product contract, record
the checks that were actually run, and keep current documentation aligned with
the code.

## Before changing code

Start with [`AGENTS.md`](./AGENTS.md), then read the owners of the surface you
will change:

- [`PRODUCT.md`](./PRODUCT.md) for product terminology and durable behavior;
- [`DEVELOPMENT.md`](./DEVELOPMENT.md) for environment, ports, setup, and local
  service commands;
- [`web/docs/README.md`](./web/docs/README.md) for canonical Web work;
- [`server/README.md`](./server/README.md) and [`jobs/README.md`](./jobs/README.md)
  for the Python services;
- [`docs/architecture/`](./docs/architecture/) for service and data ownership;
- [`deploy/production/README.md`](./deploy/production/README.md) for the current
  production boundary.

Do not begin by copying behavior from legacy `client/`. `web/` is the canonical
frontend development target and has an intentionally independent product and
architecture contract.

## Daily workflow

1. Start from an up-to-date `main` and create a short-lived task branch. Agent
   branches use the configured `codex/` prefix; human branches should use a
   similarly descriptive name.
2. Inspect the current implementation, tests, generated artifacts, and owning
   documentation before editing. Do not infer a missing contract from UI alone.
3. Keep changes within the owning service or feature. Cross-service behavior
   must follow the documented data owner and public API.
4. Run focused checks while developing and the complete gate for every changed
   surface before handing off. Do not repeatedly run unrelated suites merely as
   a substitute for targeted evidence.
5. Update invalidated current-state documentation and any required ADR in the
   same change.
6. Review the exact diff, create a coherent commit, and push the branch so a
   completed recovery point is not left only in a local worktree.
7. Open or update a pull request, complete its impact and verification fields,
   resolve review threads, and wait for required CI before merge.

Daily start commands bind to fixed loopback ports and must never install
dependencies or run migrations. Install dependencies and apply migrations only
through the explicit procedures in `DEVELOPMENT.md`.

## Branches, commits, and history

- Do not commit directly to `main`; merge through a pull request.
- Keep one independently reviewable outcome per branch. Split unrelated product,
  refactor, governance, and formatting work.
- Use concise commits in the form `type(scope): summary` where practical, for
  example `feat(reader): add anchored discussion markers` or
  `docs(governance): centralize architecture decisions`.
- Commit each verified recovery point in a multi-step change. Do not squash away
  useful checkpoints locally; GitHub performs the repository's final squash
  merge into `main`.
- If review requires rewriting a published branch, use `--force-with-lease`
  only after confirming the remote has not moved. Never use raw `--force`.
- Preserve other contributors' work in a dirty worktree. Stage only files owned
  by the current change.

## Verification

The root gate runner is the canonical command interface:

```bash
./scripts/run-gates.sh <server|jobs|shared-packages|web|client|deployment|docs|all>
```

It verifies an already prepared checkout and has no dependency-installation,
migration, or persistent service-startup side effects. Browser-test runners
may create and clean up an ephemeral web server inside their lane. Use the
narrowest relevant target during development. Run `all` for repository-wide
governance, dependency, or release-contract work and before a main merge whose
changes span the complete repository.

The owning guides describe individual leaf commands and test responsibilities.
In particular, Web changes distinguish Unit, Storybook browser, and Playwright
coverage; Server and Jobs run Ruff format checks, Ruff lint, mypy, and pytest.
Generated OpenAPI and design-token artifacts are changed through their source
and regenerated, never edited directly.

Record the exact commands and outcomes in the pull request. Real-provider smoke
tests are opt-in and never replace deterministic tests. A skipped, unavailable,
or credential-gated check must be reported explicitly.

The repository also provides an opt-in `pre-commit` configuration for staged
whitespace, YAML/TOML, large-file, Ruff, and shared-workspace checks. Enable it
explicitly with `pre-commit install` after preparing the documented Python
environments. Hooks stay intentionally fast and never replace the affected
surface gate or CI.

## Pull requests

A pull request should contain one clear outcome and enough evidence to review
it without reconstructing local context. Complete the repository template:

- summarize behavior and architectural intent;
- identify API, database, shared-package, documentation, visual, and production
  effects;
- list the exact checks run;
- attach visual evidence for user-interface work;
- link an ADR only when the change makes or supersedes a consequential decision;
- identify deferred work without presenting it as already delivered.

Do not merge with unresolved review threads, a stale base, or a failing required
check. `main` uses linear history and squash merges. Passing CI proves only the
surfaces represented by its required aggregate; it is not authorization to run
the manual production Release workflow.

## Where information belongs

Keep one canonical home for each kind of information:

| Record                                              | Purpose                                                                                     |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `AGENTS.md`                                         | Mandatory repository rules and navigation for coding agents                                 |
| `CONTRIBUTING.md`                                   | Human development, branch, commit, pull-request, and verification workflow                  |
| `DEVELOPMENT.md`                                    | Environment, installation, fixed ports, startup, and migration commands                     |
| Product, architecture, feature, and service docs    | Current behavior and ownership                                                              |
| Shared-package README                               | Public package behavior, consumers, dependency direction, and limitations                   |
| [`docs/decisions/`](./docs/decisions/README.md)     | Why a consequential decision was made and which alternatives lost                           |
| Pull request                                        | Scope, review context, impact declaration, and verification evidence for an ordinary change |
| [`docs/postmortems/`](./docs/postmortems/README.md) | Learning and follow-up from a serious incident or repeated systemic regression              |

Do not use an ADR as a live runbook or restate current implementation details in
several guides. When the implementation changes, update the current-state owner;
when the underlying durable choice changes, add a superseding ADR.

## Pre-release and production safety

Until release readiness is declared by an explicit decision, public product API
and `scholens` schema changes are reset-first: converge on one contract and
remove superseded routes, DTOs, columns, fixtures, and tests together. Do not add
compatibility layers solely to preserve disposable pre-release product data.
Never drop, reset, or assume ownership of the independently managed `auth`
schema.

Canonical `web/` is not yet the frontend used by the production Release and
Compose package. Production still builds and serves legacy `client/`. A merge to
`main` does not itself create a release, authorize deployment, or complete the
Web production cutover.

Never commit credentials, generated provider responses containing sensitive
content, private PDFs, ignored runtime environment files, or production
resource identifiers intended to remain secret.
