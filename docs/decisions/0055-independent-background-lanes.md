# ADR 0055: Independent interactive and batch admission

- Status: Accepted
- Scope: Personal EC2 deployment
- Supersedes: ADR 0054 global serialization and document worker lifetime

## Problem

A shared global admission slot makes interactive PDF imports wait behind up to
thirty minutes of automatic ingestion, despite available host resources. Each PDF
also pays worker startup costs. Pending deliveries must survive the rollout.

## Decision

Keep the shared host and online services, but place Scholens background user work
in Platform's interactive lane, independently of automatic Scholight ingestion.
Each lane admits one task after physical and ECS reservation checks. Under capacity
pressure, batch work yields first using its existing durable cancellation contract.

Container hard limits remain unchanged. Placement uses soft reservations instead
of reserving the aggregate hard ceiling twice. Document processing uses one ONNX
thread and bounded reuse: five deliveries or five minutes of acceptance, followed
by settlement of the current delivery. No PDF is interrupted by that time window.

## Alternatives considered

- Keep global serialization: avoids concurrency but retains the observed queue delay.
- Add separate hosts: provides stronger isolation but adds a fixed operating cost.
- Keep workers permanently resident: avoids cold starts but reserves idle capacity.

## Consequences

Global one-task admission lets a thirty-minute automatic ingest hold up a user
upload even when CPU, memory and disk have capacity. Repeated per-message process
startup further reduces useful throughput. Independent lanes and bounded reuse
remove those avoidable delays without a new host's fixed cost. Same-host peak
capacity is still finite; observed parallel canaries and batch preemption remain
necessary. Independent machines would provide a stronger fault boundary.

Jobs remain owned by their product queues, leases, callbacks and idempotency keys.
Platform state is not a business ledger. Existing one-shot images and registrations
remain usable during the expand/adopt rollout; Platform owns its state compatibility
adapter. Rollback reduces new concurrency before draining and restoring workers,
never deleting pending messages or restoring a stale database snapshot.
