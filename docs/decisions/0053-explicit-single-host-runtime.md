# ADR 0053: Explicit single-host runtime endpoints

## Problem

The personal-account migration consolidates compute, PostgreSQL, and Valkey on one
EC2 host while retaining ECS workload roles. Existing production hostname validation
accepts only RDS and ElastiCache. Disabling production validation would also remove
credential and TLS guarantees and could accidentally route workloads to local services.

## Decision

Add an explicit `RUNTIME_DEPLOYMENT_MODE=single-host` at Server and Jobs composition
boundaries. In production it accepts only the reviewed private namespace
`personal.svc.sanchezcloud`; the default `managed` mode preserves existing hostname
rules. Unknown modes fail closed. The runtime-contract package remains framework- and
environment-independent, receiving this selection as an argument.

Keep TLS and non-empty cache credentials mandatory. Database URLs retain `verify-full`
and an explicit CA path. Deployment must provision and mount the private trust material;
the mode does not disable certificate verification. Local development retains its
existing independent isolation checks.

## Alternatives considered

- Disable production validation: rejected because migration must preserve the security contract.
- Pretend the self-hosted services are RDS/ElastiCache: rejected because DNS and TLS identity
  should describe the actual deployment.
- Duplicate Server and Jobs validators: rejected because runtime policy would drift.

## Consequences

Existing deployed consumers remain compatible because the new argument defaults to
`managed`. There are no HTTP, schema, queue-envelope, or user-facing behavior changes.
The single-host path can be activated only by explicitly configured new infrastructure.
The migration does not change production DNS or existing database connections.
