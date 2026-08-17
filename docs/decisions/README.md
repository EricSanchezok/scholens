# Architecture Decision Records

This directory is the repository-wide record of consequential engineering
decisions. An ADR explains **why** Scholens selected a durable architecture,
product-contract, data-ownership, runtime, or development-governance rule and
what alternatives it rejected. It is not the current operating manual.

Current facts have one canonical home:

- repository and service architecture belongs under `docs/architecture/` or
  the owning service README;
- frontend feature behavior belongs in `web/docs/*-experience.md` and shared
  frontend rules belong in the Web engineering handbook;
- shared-package public behavior, consumers, and limitations belong in that
  package's README;
- local commands and environment behavior belong in `DEVELOPMENT.md`;
- production operations belong in `deploy/ecs/README.md`.

Write an ADR before deliberately changing a foundational rule such as adding a
global state library, a primitive or icon system, a shared package, a
cross-service event mechanism, a token authority, an API transport, a durable
data owner, or a release boundary. Ordinary bug fixes, local refactors, and
implementation details belong in the pull request and affected current-state
documentation instead.

Name records `NNNN-short-decision-name.md`. Every new or superseding ADR must
contain `Problem`, `Decision`, `Alternatives considered`, and `Consequences`.
`Validation` is optional but recommended when a machine-checkable acceptance
signal exists. Once accepted, do not rewrite the substantive decision history;
add a later ADR that supersedes it. Mechanical format or link repairs must not
change what the accepted record decided.

## Accepted decisions

- [ADR 0001: Independent web application](./0001-independent-web-application.md)
- [ADR 0002: DTCG token source of truth](./0002-dtcg-token-source-of-truth.md)
- [ADR 0003: Generated public API contract](./0003-generated-public-api-contract.md)
- [ADR 0004: Locale-neutral application internationalization](./0004-locale-neutral-next-intl.md)
- [ADR 0005: Memory-token authentication session](./0005-memory-token-auth-session.md)
- [ADR 0006: Fixed local-development port block](./0006-local-development-port-contract.md)
- [ADR 0007: Generated design-system contract](./0007-generated-design-system-contract.md)
- [ADR 0008: Single Conversation agent](./0008-single-conversation-agent.md)
- [ADR 0009: Conversation turns own response variants (superseded)](./0009-turn-response-variants.md)
- [ADR 0010: Turn suggestions and two-stage response readiness](./0010-turn-suggestions-and-response-ready.md)
- [ADR 0011: Library projections and signed keyset pagination](./0011-library-projections-and-keyset-pagination.md)
- [ADR 0012: Atomic paper-ingestion acceptance and cooperative cancellation](./0012-atomic-paper-ingestion-lifecycle.md)
- [ADR 0013: Reader context and anchor contracts](./0013-reader-context-and-anchor-contracts.md)
- [ADR 0014: Anchored annotation threads and Project audiences](./0014-annotation-thread-collaboration.md)
- [ADR 0015: Durable Reader selection translation](./0015-durable-reader-selection-translation.md)
- [ADR 0016: Lossless Reader reflow and lazy full translation](./0016-lossless-reader-reflow-and-lazy-translation.md)
- [ADR 0017: Evidence-driven Reader reflow and controlled document translation](./0017-evidence-driven-reader-reflow.md)
- [ADR 0018: Conversation prompts form durable selected branches](./0018-conversation-prompt-branches.md)
- [ADR 0019: User-owned integration credentials and explicit AI reflow](./0019-user-owned-integration-credentials.md)
- [ADR 0020: Separate paid subscriptions from product-granted entitlements](./0020-separate-paid-and-product-entitlements.md)
- [ADR 0021: Semantic Web motion system](./0021-web-motion-system.md)
- [ADR 0022: Immutable ECS release boundary](./0022-immutable-ecs-release-boundary.md)
- [ADR 0023: Agent-native Scholens knowledge boundary](./0023-agent-native-scholens-mcp.md)
- [ADR 0024: Shared Aliyun account and durable product email](./0024-shared-aliyun-account-and-durable-product-email.md)
- [ADR 0025: Read-only Zotero integration across Server and Jobs](./0025-read-only-zotero-integration.md)
- [ADR 0026: Production contract and schema evolution](./0026-production-contract-evolution.md)

ADR 0026 supersedes only the pre-release reset-first/disposable-data clauses
in earlier records and amends ADR 0022's exact-migration-head rollback rule.
All unrelated decisions in those records remain accepted.

## Template

```markdown
# NNNN — Decision title

Status: Proposed | Accepted | Superseded
Date: YYYY-MM-DD
Owners: names or team

## Problem

What concrete problem and constraints require a decision?

## Decision

What will we do? State boundaries and non-goals.

## Alternatives considered

What credible alternatives were rejected and why?

## Consequences

What becomes easier, harder, or newly required?

## Validation

How will we know the decision works, and when should it be revisited?
```
