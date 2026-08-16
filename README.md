# Scholens

[简体中文](./README.zh-CN.md)

Scholens is a pre-release research workspace for building a durable, traceable
reading and analysis workflow around scholarly papers. The canonical product is
the Next.js application in `web/`, backed by the FastAPI service in `server/`
and asynchronous workers in `jobs/`.

## What is implemented

- A single contextual conversation experience across the home workspace,
  projects, and individual papers.
- A personal paper library with PDF, DOI, arXiv, direct-URL, and Zotero
  ingestion paths.
- Project workspaces for organizing papers, conversations, generated outputs,
  and collaborator-visible research context.
- A document reader with PDF navigation, source-grounded conversations,
  anchored annotation threads, selection translation, and evidence-preserving
  reading reflow.
- User-owned connections for optional search, parsing, and research providers.

The stable product principles are documented in [PRODUCT.md](./PRODUCT.md).
Executable contracts, generated API schemas, and tests remain the authority for
the exact behavior available in a checkout.

## Repository layout

| Path          | Responsibility                                      |
| ------------- | --------------------------------------------------- |
| `web/`        | Canonical product frontend                          |
| `server/`     | FastAPI application and synchronous product APIs    |
| `jobs/`       | Asynchronous ingestion and generation workers       |
| `packages/`   | Shared Python contracts and infrastructure packages |
| `client/`     | Legacy comparison frontend; not a production target |
| `deploy/ecs/` | Production ECS/Fargate release infrastructure       |

## Development

Start with the documentation index in [docs/README.md](./docs/README.md).

- [DEVELOPMENT.md](./DEVELOPMENT.md) covers prerequisites, environment
  variables, fixed local ports, setup, and startup commands.
- [CONTRIBUTING.md](./CONTRIBUTING.md) defines the branch, review, documentation,
  and verification workflow.
- [AGENTS.md](./AGENTS.md) contains repository boundaries and mandatory agent
  guardrails.

The root verification entry point is:

```bash
./scripts/run-gates.sh <server|jobs|shared-packages|web|client|deployment|docs|all>
```

The runner verifies a prepared checkout. It does not install dependencies,
start persistent services, or apply migrations.

## License and provenance

Scholens is distributed under the [GNU Affero General Public License,
version 3](./LICENSE). See [NOTICE.md](./NOTICE.md) for the required provenance
and modification notice. Separately licensed evaluation fixtures are documented
beside those fixtures.
