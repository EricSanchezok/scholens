# ADR 0054: Admit background workers on the shared host

- Status: Accepted
- Scope: Personal EC2 deployment

## Problem

Idle background processes retain substantial memory on the same host as online
chat, search and PostgreSQL. Uncoordinated heavy jobs can exhaust shared headroom.

## Decision

Keep API, web, and conversation workers resident. Document, research, and maintenance
workers use `SCHOLENS_WORKER_ONE_SHOT=1` only when `BackgroundMode=admitted`.
They reserve one message, cancel further consumption, and exit after the parent
request acknowledges or rejects that delivery. Empty workers exit after 30 seconds.
Concurrency and prefetch must both be one. A broker reconnect closes the worker
rather than reserving another message while its prior lease is unresolved.

Platform owns host admission; Scholens owns queue references, exact task revisions,
IAM grants and this worker lifecycle. The product registration contains no secrets
and grants the host only queue depth reads, exact RunTask and PassRole permissions.
Document memory remains 2,560 MiB, plus 64 MiB for the existing temporary-volume
initializer. Research and maintenance similarly include their initializer in the
task admission limit. Online service memory limits remain unchanged.

## Rollout and recovery

The default remains `resident` to preserve existing deployments. Publish and verify
the one-shot image, install disabled registrations, drain resident workers, switch
`BackgroundMode` to `admitted`, update registrations to the resulting immutable task
revisions, and enable host admission. Never enable both consumers simultaneously.
To roll back, stop admission and wait for the active task to settle before restoring
resident workers. Queue messages, database leases, callbacks, retries and deduplication
remain authoritative; controller state is not a business task ledger.

A stopped background task must retain its broker delivery or recovery lease. The
shared controller uses available memory, database health and disk headroom before
launch and stops only its admitted task under memory pressure. This is resource
isolation, not host or database high availability.

## Alternatives considered

Resident workers retain the previous behavior but reserve idle memory. Additional
hosts provide a stronger fault boundary with additional fixed cost. Independent
queue-triggered launches do not enforce a shared memory budget. A single host
admission loop is the selected tradeoff for this deployment.

## Consequences

Background work may wait roughly one polling interval plus container startup.
Long-running work delays other background jobs. Durable retries and daily backups
remain necessary, and the host and database remain shared failure points.

## Verification

Use real isolated RabbitMQ with prefork to prove that exactly one delivery settles
and another remains queued. Keep existing retry, duplicate-delivery and callback
regressions. Test host admission recovery separately in Platform; verify production
SQS behavior with a disposable queue before enabling business queues.
