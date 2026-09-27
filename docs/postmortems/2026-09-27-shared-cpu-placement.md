# Shared CPU reservation starvation during a Scholens release

- Date: 2026-09-27
- Status: Final
- Severity: SEV-2
- Owners: Scholens and SanchezCloud Platform

## Summary

A Scholens application rollout temporarily freed the old API task's CPU reservation.
The shared background controller admitted another product's work into that gap,
while the replacement API could not be placed. The API eventually recovered after
a brief pause in new background admissions. Subsequent investigation found a second
problem: the resident topology itself left less CPU than two registered background
workloads required, so those workloads could run only when an online service was absent.

The recovery now combines a stable-online-service admission condition with a
tested Scholens resident CPU budget. Neither protection alone addresses both failure
modes. The original application image remains immutable; the capacity correction is
a separately reviewed deployment control change.

## Impact

The bounded host monitor observed approximately 359.54 seconds of API health
unavailability and 18.06 seconds of Web health unavailability during the application
cutover. These observations are not a count of affected users or failed public
requests. The monitoring sample recorded no cgroup OOM kills. No other product's
task was manually stopped during recovery.

This deployment model intentionally stops the old task before starting its
replacement to respect static host ports and memory constraints. Later cohort and
CPU-only changes still produced approximately 46.23 and 40.17 seconds of API health
unavailability respectively. Different change scopes prevent treating those numbers
as a controlled performance comparison or a zero-downtime claim.

## Detection

The release continuity monitor detected the API gap. ECS service events reported
insufficient CPU. The controller journal showed background admissions during the
replacement interval. Existing stopped-task alerts could not cover a placement
failure that prevented a task from being created.

## Timeline

All times below are UTC on 2026-09-27.

- 21:26:01: a scheduled Scholight ingest task was admitted.
- 21:26:11: the previous Scholens API task stopped during the reviewed rollout.
- 21:26:21: ECS reported insufficient CPU for replacement placement.
- 21:27:31: the admitted ingest task finished successfully.
- 21:30:01: another ingest task was admitted.
- During recovery: new background admissions were paused for 85.27 seconds, then
  the controller was restored. Already running product tasks were left to finish.
- 21:31:37: the replacement API task started; health subsequently recovered.
- The online-service admission guard was deployed before the next cohort change.
- A full desired-service inventory found 1,584 of 2,048 CPU units reserved, leaving
  only 464 for registered ingest and metadata tasks that each required 512.
- A reviewed API reservation adjustment reduced the resident total to 1,456,
  leaving 592 units. All eight enabled background registrations individually fit;
  an ingest task was observed running with all online services healthy.

## Contributing factors

- CPU shares serve both as relative scheduling weights and ECS placement
  reservations. Raising the API weight without summing every desired resident
  service removed another product's steady-state placement capacity.
- The admission controller previously treated current remaining ECS resources as
  spare capacity without checking whether an online service was being replaced.
- Product-level template checks did not enforce a resident CPU ceiling that
  preserved a background slot for another registered consumer.
- Monitoring covered stopped tasks but lacked ECS service placement events.
- The first attempt to deploy the new alert failed because CloudFormation
  truncated its generated name beyond the executor's IAM resource prefix. The
  manual workflow initially reported success after dispatch, before the stack
  rolled back. Both the name-to-policy boundary and final apply state needed
  verification. A subsequent apply stopped before execution because the new
  waiter logic assumed that DescribeChangeSet returned ChangeSetType. The
  request field is absent from that response. Entry-point tests now use the real
  response shape and derive the waiter from the observed stable stack state.

## Resolution and recovery

The controller now discovers all desired online services and blocks new background
admissions while any deployment is incomplete, a task is pending, or desired capacity
is missing. Inventory failure also blocks new admissions while existing work continues
to reconcile. This is an observed-state guard, not an atomic lock with external ECS
operations.

Scholens now budgets 592 resident CPU units and tests a ceiling of 640, preserving
896 units for other residents and a 512-unit background slot on the 2,048-unit host.
The API keeps higher scheduling priority than the inference owner. Total admitted
background concurrency remains one; failed original mixed-load latency thresholds
are retained and do not justify increasing it.

The new placement alert uses an explicit name inside the existing permission
scope. Shared infrastructure apply waits for CloudFormation success and verifies
the exact reviewed change-set ID, so rollback, timeout or another completion fails
the workflow. The live cluster-scoped rule, bounded notification payload and exact two-rule SNS
publisher grant were verified after the final matching change set completed. These
checks are separate from event-pattern tests.

## Corrective actions

| Action | Owner | Status | Tracking link |
| --- | --- | --- | --- |
| Block background admissions during online-service deployment | Platform | Deployed and observed | [Platform #4](https://github.com/EricSanchezok/sanchezcloud-platform/pull/4) |
| Preserve shared steady-state CPU capacity with a topology regression | Scholens | Deployed and observed | [Scholens #204](https://github.com/EricSanchezok/scholens/pull/204) |
| Detect placement failures independently of task exits | Platform | Deployed and verified | [Platform #5](https://github.com/EricSanchezok/sanchezcloud-platform/pull/5) |
| Verify rule naming scope and actual infrastructure apply completion | Platform | Deployed and verified | [Platform #6](https://github.com/EricSanchezok/sanchezcloud-platform/pull/6) |
| Regress the real CloudFormation response and stable-stack boundary | Platform | Deployed and verified | [Platform #7](https://github.com/EricSanchezok/sanchezcloud-platform/pull/7) |

## Lessons

Capacity review must use the full desired resident topology and every enabled
background registration. A deployment gap is reserved recovery capacity. Relative
priority, memory safety, placement feasibility and measured foreground latency are
separate constraints. Preserve failed measurements and release interruptions in
the acceptance record, and distinguish workflow dispatch from verified deployment.
