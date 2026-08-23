# Scholens documentation

This index identifies the current owner for each kind of repository fact. Git
history, not an archive directory, preserves superseded audits, marketing copy,
and implementation snapshots.

## Start here

| Need                                   | Canonical source                                                                                                               |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Product direction and durable behavior | [`PRODUCT.md`](../PRODUCT.md)                                                                                                  |
| Local environment, ports, and commands | [`DEVELOPMENT.md`](../DEVELOPMENT.md)                                                                                          |
| Contribution and review workflow       | [`CONTRIBUTING.md`](../CONTRIBUTING.md)                                                                                        |
| Agent navigation and guardrails        | [`AGENTS.md`](../AGENTS.md)                                                                                                    |
| Canonical frontend engineering         | [`web/docs/README.md`](../web/docs/README.md)                                                                                  |
| Backend API and capability ownership   | [`server/README.md`](../server/README.md) and [`architecture/backend-capabilities.md`](./architecture/backend-capabilities.md) |
| Async processing                       | [`jobs/README.md`](../jobs/README.md)                                                                                          |
| Shared Python packages                 | [`packages/README.md`](../packages/README.md)                                                                                  |
| Production release                     | [`deploy/ecs/README.md`](../deploy/ecs/README.md)                                                                              |

## Architecture and decisions

- [`architecture/data-ownership.md`](./architecture/data-ownership.md) defines
  storage and service ownership.
- [`architecture/backend-capabilities.md`](./architecture/backend-capabilities.md)
  defines the current backend capability boundaries.
- [`architecture/contract-evolution.md`](./architecture/contract-evolution.md)
  defines production API, MCP, job, and database compatibility rules.
- [`decisions/README.md`](./decisions/README.md) indexes accepted architecture
  decisions. ADRs explain why a durable choice was made; they are not live
  runbooks.
- [`postmortems/README.md`](./postmortems/README.md) defines when a postmortem is
  appropriate.

## Operational and compliance work

- [`setup/external-services.zh-CN.md`](./setup/external-services.zh-CN.md)
  documents project-specific external service setup.
- [`operations/AWS_OBSERVABILITY_SETUP.md`](./operations/AWS_OBSERVABILITY_SETUP.md)
  documents production observability provisioning.
- [`operations/mcp-tool-test-report.md`](./operations/mcp-tool-test-report.md)
  records the current end-to-end MCP tool and resource audit baseline.
- [`legal-content-review.md`](./legal-content-review.md) records the factual
  questions that must be approved before replacing public legal text.

## Maintenance rules

- Executable code, committed schemas, and tests take precedence when a current
  implementation fact conflicts with prose.
- Describe shipped behavior in current-state documentation. Put intended but
  unimplemented product direction in `PRODUCT.md` and consequential rationale
  in an ADR.
- Update the owning document in the same change that invalidates it. Do not
  copy the same command, limit, schema, or architecture contract into another
  guide without a concrete reader need.
- Do not commit screenshots or videos unless they show the current product and
  have a documented owner, source, license, usage, and verified revision.
