# 0023 — Agent-native Scholens knowledge boundary

Status: Accepted
Date: 2026-08-16
Owners: Scholens

## Problem

Research may continue for months in a Codex workspace, another Agent, or a Git
repository while papers and collaborative reading state live in Scholens. A
title-only convention cannot reliably reconnect those systems, and an
incomplete MCP surface forces Agents to bypass Scholens for ordinary
management. Exposing internet discovery again would duplicate the Agent's own
search stack and blur responsibility. Local PDFs add a different constraint:
the hosted Server cannot read a client path and most user computers have no
publicly reachable file server.

The prior model-visible catalog also lacked a uniform contract for typed
outputs, behavioral hints, resource links, destructive confirmation, and the
collaboration-management permission needed by a long-running external Agent.

## Decision

Treat a Scholens Project UUID and `scholens://projects/{project_id}` URI as the
durable knowledge binding for an external research workspace. Project create
and get operations return a ready-to-paste repository binding and Web URL.

Maintain one canonical Agent-facing catalog for stored knowledge, known-source
ingestion, organization, collaboration, annotations, jobs, and existing
outputs. The in-product Agent and inbound MCP select the same definitions.
Internet literature discovery and output generation are not part of this
catalog. Each definition owns its input and output schema, permission,
execution kind, behavioral annotations, and decision-oriented description.

Expose bounded MCP resources for durable Scholens objects. Add a distinct
`manage` Access Key permission for collaboration and public-sharing operations.
Require state-bound, expiring, single-use confirmation for destructive,
externally visible, and access-changing operations. Persist replay results only
when their contents are safe for durable storage; confirmation challenges,
plaintext public bearer tokens, and signed upload URLs remain transient.

Use a two-stage direct-upload protocol for PDF bytes. The hosted server creates
a checksummed staging session and signed PUT URL. Browsers upload directly. The
official local stdio bridge replaces the remote preparation primitive with one
path-aware tool that reads only files beneath explicit MCP roots, uploads bytes
without forwarding the Scholens credential, and calls the same ingestion tool.
Remote MCP and object-upload URLs require HTTPS outside loopback development.
Each ingestion claim carries a generation-specific lease token, preventing a
stale operation from consuming or releasing a newer claim.

## Alternatives considered

- Give Scholens MCP its own web-search tools. Rejected because the external
  Agent already owns discovery and source choice; duplicate discovery creates
  conflicting ranking, provenance, and provider configuration.
- Expose only paper CRUD. Rejected because Projects, membership, annotations,
  jobs, and durable outputs are necessary to maintain a research corpus over
  months without manual repair in the Web UI.
- Bind repositories by Project title. Rejected because titles are mutable and
  not unique.
- Send local paths to the hosted MCP server or require a client HTTP server.
  Rejected because server paths are meaningless, paths disclose local context,
  and requiring a public IP is unsafe and impractical.
- Accept destructive booleans such as `confirm=true`. Rejected because a stale
  or copied boolean is not bound to the actor, credential, arguments, current
  state, or a reviewed impact.
- Maintain separate internal and external tool implementations. Rejected
  because schemas, permissions, and business behavior would drift.

## Consequences

External Agents can restore a Project from repository guidance, import known
papers, search and cite stored material, manage collaboration, and maintain
discussions without Scholens becoming their discovery engine. Users can open
the same records in the Web Reader for deep reading.

The catalog and tool count become reviewed contracts. Adding a model-visible
capability requires metadata, permission, typed result, tests, and a decision
about whether it belongs to both profiles. Risky actions require a two-call UI
or Agent interaction. Direct upload introduces temporary database rows, bucket
lifecycle rules, bounded expired-row cleanup, checksum verification, and a
separately packaged local connector, but it does not introduce a second
ingestion path or require inbound client networking.

## Validation

- Catalog tests enforce profile symmetry, exact intentional differences, tool
  metadata, parameter descriptions, and permission visibility.
- MCP protocol tests verify structured output, behavior hints, resources, and
  reauthorization.
- Confirmation tests verify actor/credential/argument/state binding, expiry,
  hashing, single use, and omission of raw challenges from replay storage.
- Upload and local-connector tests verify root confinement, symlink rejection,
  metadata/checksum flow, lease ownership, URL policy, byte transfer, and
  absence of credential forwarding.
- `./scripts/run-gates.sh server`, `mcp-connector`, `web`, `deployment`, and
  `docs` own the affected deterministic checks.
