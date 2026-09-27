# 0061 — Fair bounded job publication

Status: Accepted
Date: 2026-09-27
Owners: Scholens Jobs

## Problem

Publishing an entire user's bulk import into a serial broker queue makes later
users wait behind that burst. Worker prefetch alone cannot restore fairness once
the messages are published. Separate resource stages also need independent budgets.

## Decision

Keep the accepted backlog in PostgreSQL and publish at most two unfinished jobs
per queue, one per requester. A durable requester cursor provides round-robin turns
within each queue, while each requester's oldest eligible job retains precedence.
A nonblocking transaction advisory lock coordinates concurrent publishers. Network
publication remains outside the reservation transaction. Existing publish leases,
job IDs, execution fences and terminal facts retain their established ownership.

Gate adoption with `JOB_DISPATCH_FAIRNESS_ENABLED`, after the additive cursor/index
migration. All publishers must adopt the gate before asserting the bound. Existing
oversized broker backlogs drain naturally; no queue purge or message inspection is
required. N-1 publishers can still execute existing jobs with the gate disabled.

## Alternatives considered

- Worker prefetch one bounds local buffering but leaves bulk queue ordering intact.
- In-memory rotation loses fairness after restart and cannot coordinate API replicas.
- One queue per user expands operational state and couples infrastructure to accounts.
- Publishing every accepted job transfers scheduling authority to a FIFO backlog
  where cancelled, reprioritized and newly arriving user work cannot be handled well.

## Consequences

Accepted jobs may remain pending in PostgreSQL. Queue age alone no longer measures
the full waiting backlog; outbox queue age and job status are also required. Two
slots permit one running delivery and a warm successor while bounding competing
users' published work. A slow or unavailable worker stops further publication to
its queue while independent queues continue. The persisted cursor is expendable
ordering metadata; job completion and execution fencing remain authoritative.

## Validation

Real PostgreSQL tests cover a 40-job burst followed by a new requester, concurrent
publishers, an expired publish lease, cancellation, independent queues and N-1
publisher behavior. The migration is additive and Alembic detects no model drift.
