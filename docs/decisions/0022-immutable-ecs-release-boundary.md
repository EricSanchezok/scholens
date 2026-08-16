# 0022 — Immutable ECS release boundary

Status: Accepted
Date: 2026-08-16
Owners: Scholens

## Problem

Scholens inherited an unreleased EC2 and Docker Compose path from OpenPaper. It
did not match the shared SanchezCloud AWS account, the Scholight production
conventions, or Scholens' actual Web, API, and asynchronous workloads. Mutable
image tags, rebuild-at-deploy behavior, broad operator credentials, colocated
migrations, and host-level workers would make a first release difficult to
audit, scale, or roll back. Retained data planes and replaceable runtime
resources also have different change and recovery risks.

## Decision

Production has three CloudFormation stacks. An administrator-owned bootstrap
stack owns both CloudFormation execution roles, the ECS execution role, scoped
GitHub and diagnostic roles, immutable permissions boundaries, and the runtime
execution policies. The foundation execution role can reconcile the retained
data plane but cannot mutate IAM; the runtime role can manage only its exact
boundary-constrained task/scheduler roles and cannot change or remove a
boundary. The protected foundation stack owns retained KMS keys, versioned
buckets, immutable ECR repositories, SQS queues, Valkey, secret containers,
security groups, and alerts. A replaceable runtime stack owns an IPv4 ALB/WAF
boundary, separate Web and API services, three queue-specific ECS worker
services, Scheduler tasks, autoscaling, logs, alarms, and dashboards on the
shared production cluster.

CI publishes three digest-qualified linux/amd64 images. Web runtime and its
private source-map index come from one BuildKit build graph. Exact digest ECR
scans fail closed on incomplete scans and unwaived HIGH/CRITICAL findings. A
source-bound, versioned manifest records the image and scan digests, migration
graph head, public build values, API and template checksums, dependency
revision, and source-map aggregate. Release objects use conditional writes in
a compliance Object Lock bucket; a different object at an existing key is a
release failure.

Publishing, database migration, foundation update, and production deployment
use separate GitHub environments and least-privilege OIDC roles. Deployment
accepts only a manifest whose account, Region, repository, digest, source, and
public configuration match the selected `main` commit. Product migration is a
one-off ECS task with a bounded diagnostic wait and never runs as an API startup
side effect. Services can remain hard-disabled at zero for first migration.
Release orchestration and all verifiers always execute from the workflow's
trusted `main` control plane; candidate and rollback commits are parsed only as
manifest-bound source/template data. Parameter overrides are intersected with
the selected template so older compatible templates retain supported existing
stack values without executing their historical release scripts.
Migration success writes an immutable per-release attestation and a versioned
current database contract. Release, database, and foundation workflows share
one production control-plane concurrency group, so the checked current proof
cannot change between verification and deployment. Rollback or automatic
candidate-verification recovery may restore an older app only when its migration
and Identity contracts still match the current database; otherwise the candidate
is disabled at zero.

The public proxy contract keeps Uvicorn from consuming forwarding headers.
Application middleware verifies the original peer against the imported VPC
CIDR, then accepts exactly one Cloudflare-overwritten `CF-Connecting-IP` value
for logs and rate limits. WAF request sampling is disabled because normal
requests contain the origin secret; aggregate metrics remain enabled.

Scholight owns the retained MCP delegation secret. Its foundation exports the
dedicated secret ARN and exact KMS key ARN; Scholens receives only those values
and cannot read Scholight's core secret. Cross-product rollout therefore starts
with the Scholight foundation and runtime before creating Scholens.

## Alternatives considered

- Continue the inherited EC2/Compose release. Rejected because host patching,
  process placement, scaling, and rollback would remain manual and couple
  unrelated workloads.
- Put every retained and runtime resource in one stack. Rejected because normal
  releases would expose databases, queues, buckets, and keys to unnecessary
  replacement and deletion risk.
- Build or tag images during deployment. Rejected because the deployed bytes
  would no longer be the reviewed CI artifact.
- Run every worker in one ECS service. Rejected because document, research,
  and maintenance queues have different capacity, timeout, cost, and failure
  profiles.
- Copy Scholight's delegation value into a Scholens secret or permit Scholens
  to read Scholight core. Rejected because it creates two authorities or grants
  unrelated secret access.

## Consequences

First release requires an ordered platform bootstrap: deploy the Scholight
delegation secret and runtime, create the administrator-owned Scholens IAM
bootstrap, create the tagged foundation through its restricted execution role,
populate external secrets and database roles, validate ACM/Cloudflare, publish
a manifest, deploy disabled runtime, migrate, then enable services and finally
the scheduler. Rollback selects an older immutable manifest only when the live
database contract permits it; it does not reverse database migrations or
recreate deleted retained data.

Operational capacity is independently adjustable and workers can scale to
backlog. This adds explicit AWS IAM, CloudFormation, alarm, and source-map
contracts that must stay under automated validation. Cloudflare DNS and origin
header configuration, secret values, RDS role creation, GitHub environment
approval, and ACM DNS validation remain intentional human-controlled gates.

## Validation

The deployment gate lints all three templates, keeps both inline bootstrap
templates below 48,000 raw UTF-8 bytes, rejects aliases, validates IAM and
bucket-policy boundaries,
checks disabled scaling and alarms, verifies manifest registry and migration
graph failures, and exercises runtime endpoint validation. CI builds all three
images and runs the API image's real migration path twice against isolated
least-privilege roles before a manifest can be published.
