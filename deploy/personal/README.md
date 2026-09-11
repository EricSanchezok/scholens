# Personal-account production deployment

Production uses account `669409472143`, region `ap-south-2`. Normal releases are
manual and use the personal workflows; retired workflows are archived outside Actions.
`scripts/personal_deployment.py` renders three CloudFormation JSON templates from the
canonical product contracts under `deploy/ecs/`; generated files are deployment
artifacts, not a second editable copy of those contracts.

```bash
server/.venv/bin/python scripts/personal_deployment.py foundation --output foundation.json
server/.venv/bin/python scripts/personal_deployment.py bootstrap --output bootstrap.json
server/.venv/bin/python scripts/personal_deployment.py runtime --output runtime.json
./scripts/run-gates.sh deployment
```

The renderer has no AWS side effects. Supply the expected account ID and current
Platform outputs, inspect a CloudFormation change set, and execute it only against the
personal account. Use the canonical three stack names within that account so scoped
IAM policies continue to match. Large templates must be uploaded to the product's
release bucket before CloudFormation submission. Never apply these artifacts to the
old production account.

## Ownership and isolation

Platform supplies the EC2 host, network, ECS cluster, encrypted volumes, common HTTPS
entrypoint and `personal.svc.sanchezcloud` private namespace. Account Center owns the
shared PostgreSQL process and backup/recovery configuration. Identity exclusively owns
`auth` migrations. Scholens owns its queues, storage, Valkey credentials, workload roles
and product migrations.

The retained data foundation excludes managed ElastiCache and product security groups.
Queues and secret paths use `preview` names. GitHub roles trust separate
`personal-image-publish`, `personal-infrastructure`, `personal-database`, and
`personal-preview` environments. The runtime adapter removes ALB/WAF, managed scaling,
Cloud Map registration, scheduled producers and telemetry sidecars.

Each Python workload has an independent task role. Conversation processing initially
uses the API capability policy on its own role because it runs the same application
composition. Web has no AWS task role. The host firewall must deny containers access to
EC2 instance credentials; execution-role secret injection does not grant applications
access to Secrets Manager.

## Runtime contract

Services use ARM64 EC2 bridge tasks. Web binds host port `13000`, API `18000`; the shared
entrypoint owns public HTTPS. Python tasks mount `/srv/sanchezcloud/trust` read-only at
`/run/trust`, require `private-ca.pem` for PostgreSQL verification, and use a combined
public/private CA bundle for HTTPS and Valkey TLS. Production validation stays enabled
with explicit `RUNTIME_DEPLOYMENT_MODE=single-host`.

Each service runs one task when enabled; workers retain concurrency one. Container CPU,
soft memory and hard memory limits are explicit. Deployments stop the old task before
starting its replacement (`minimumHealthyPercent=0`, `maximumPercent=100`), accepting a
short preview outage to avoid static-port conflicts and doubled memory use.

The API and conversation worker have 1,536 MiB hard limits so local semantic
embedding initialization fits alongside application imports. The document
worker has a 2,560 MiB hard limit; its original 1,280 MiB limit killed a PDF
postprocessing child while loading the model. Passage inference uses batches
of eight to avoid the larger activation peak of a 128-window batch. Soft
reservations, worker concurrency and the host size remain unchanged; verify
aggregate host memory under representative simultaneous work after rollout.

The maintenance worker reserves 256 MiB with a 512 MiB hard limit: the shared Jobs
imports exceed the original 256 MiB limit before it can consume a task. Every
personal Celery worker reports a local heartbeat and has an explicit ECS health
check, so Conversation does not inherit the API image's HTTP probe. Queue age and
failed tasks remain separate operational signals from event-loop liveness.

`ApplicationEnabled` defaults to false. Restoring a database does not authorize starting
workers or replaying copied jobs. Before enabling services, provision database/cache
TLS, restore and reconcile data, inject independent preview authentication secrets,
keep `SCHOLENS_EMAIL_DELIVERY_ENABLED=false`, configure the authenticated edge, and verify all endpoints and
queue URLs point to the intended environment. `ScholightMcpUrl` explicitly preserves
the existing external Scholight API; its production database connection is unchanged.

These templates prepare infrastructure; they are not evidence of a completed restore,
ARM64 image smoke test, application rollout or load rehearsal. Those execution results
belong in the migration record. The adapter is owned by Scholens maintainers and can be
folded into the sole deployment package after old-account cutover and decommissioning.

## Manual ARM64 image publication

`personal-publish.yml` accepts only a revision already merged into main, runs the shared
CI workflow, and uses the `personal-image-publish` environment. Configure its AWS account,
region, publishing role, preview API URL and Account Center URL from the reviewed stack
outputs. The existing repository Identity reader key is passed as a BuildKit secret.

The job runs on native ARM64, overrides both Web bake targets to ARM64, imports native
Python dependencies in the resulting images, and scans the ARM64 child digest of each
OCI index. The existing release manifest format records `linux/arm64` in each image scan;
all components must agree. CLI manifest verification defaults to `linux/amd64` for the
managed production path and requires explicit `--expected-platform linux/arm64` here.
Publishing creates no GitHub Release, version tag, runtime deployment or database write.

The personal renderer defaults `EmailDeliveryEnabled` to `false`. This suppresses
both identity email senders and the project-invitation delivery supervisor, even if
credentials are accidentally present. Set it to `true` only during the reviewed
production cutover, after restoring the production sender credentials and checking
pending invitations. Managed deployments retain the enabled default.

For production adoption, set `DomainName` to the production hostname and publish a new
merged revision with the production `PRODUCTION_API_URL` and `ACCOUNT_CENTER_URL` in
`personal-image-publish`. Web embeds these URLs at build time; reusing a preview
manifest cannot change them. Keep the personal workflow environments and existing
queue, secret, bucket and log identifiers: renaming durable resources is not part of
cutover. Preserve the old account's release path until rollback is retired.


## Private Valkey runtime

`valkey/runtime.yml` runs the pinned ARM64 Valkey image with TLS only on private host
port 6380, a 192 MiB no-eviction cache limit, 128 MiB soft/384 MiB hard container memory, AOF
and the same API/Jobs key-prefix ACLs as the managed cache. The default user is disabled.
The ECS execution role injects two Secrets Manager passwords; the process receives no
AWS role. Bootstrap hashes passwords into a private tmpfs ACL file and removes plaintext
password variables before starting Valkey. No credential appears in command arguments.

Run `valkey/prepare-host.sh` through SSM after Account Center provisions the shared CA.
It creates only the Valkey leaf certificate and data directory, and refuses partial or
expired existing material. Install `start.sh` and `valkey.conf` in
`/srv/sanchezcloud/valkey-config`, then inspect the cache change set before enabling it.
The TLS/NOAUTH health check confirms that the private listener requires authentication;
acceptance must additionally verify both role credentials and their cross-prefix denial.

## Manual personal control plane

`personal-infrastructure.yml` plans or applies updates to the existing personal
foundation. `personal-preview.yml` does the same for application tasks. Planning
retains existing parameters, renders the personal topology, and creates a persistent
CloudFormation change set. Review the artifact and its resource list, then dispatch
`apply` with that exact ARN and the same immutable control-plane revision. Apply
rejects a foreign account/region, mismatched source, resource removal, durable-resource
replacement, and managed load balancer/NAT/cache additions. Task-definition replacement
is expected. Initial IAM bootstrap and new required parameters remain administrator
operations rather than expanding the GitHub role's own authority.

The runtime accepts only merged ARM64 manifests containing the worker-heartbeat helper;
rollback candidates must meet that compatibility floor. Starting services additionally
requires a matching migration attestation and current database-contract verification.
Use the personal database workflow before planning an enabled deployment. Neither
workflow creates a GitHub Release or changes the old production environment.

`personal-database.yml` uses OIDC to run a one-off EC2 ECS migration task in the private
cluster. It exposes no PostgreSQL endpoint to a GitHub runner and grants the host no
migration secret permissions. It preserves append-only transition checks, runtime
convergence proof, immutable attestations, and retirement of the candidate task revision.
The task owns only Scholens migrations; Identity compatibility is verified independently.
All three operations share one concurrency group. The first restored database's current
attestation must be established from its successful migration proof by the operator.

Configure role variables from bootstrap outputs in their matching personal GitHub
environments, including `AWS_FOUNDATION_CLOUDFORMATION_ROLE_ARN` and
`AWS_RUNTIME_CLOUDFORMATION_ROLE_ARN`. Set `AWS_REGION` to the reviewed destination;
credentials and database passwords never appear in workflow inputs or artifacts.

### Queue alerts

Deploy `queue-monitoring.yml` once for each conversation, document, research, and
maintenance queue, supplying its queue/DLQ names from the destination foundation and
the confirmed shared alert topic from Platform. Each pair adds two standard alarms:
a visible message older than the configured waiting budget for three minutes, and any
visible dead-letter message. Missing idle SQS metrics are non-breaching. The default
waiting budget is 30 minutes for serial background work; use 60 seconds for conversation.
These alerts report delay/failure and never scale instances or replay failed work.

## Admitted background workers

[ADR 0054](../../docs/decisions/0054-admitted-background-workers.md) owns the worker
lifecycle. `BackgroundMode=resident` preserves the previous deployment. The reviewed
`admitted` mode scales only document/research/maintenance services to zero and enables
one-shot task definitions with hard aggregate memory and 0.5-vCPU limits. Deploy
`background.yml` with task revisions, role ARNs and queue outputs from this product;
its registrations are disabled by default. Platform admission must be installed and
healthy before enabling them. API, web and conversation remain independent services.
The manual runtime workflow's `background_mode` input defaults to `preserve` so an
ordinary product release keeps admission enabled. Explicit `admitted` or `resident`
changes are included in the reviewed change set. Stop competing consumers and
refresh product registrations to the new immutable task revisions before admission.

### Every subsequent product release

Manually publish a merged SHA with `personal-publish.yml`, run the protected product
migration workflow when an attestation is needed, then use `personal-preview.yml`
with `operation=plan`. Review its exact change set before `operation=apply`. Select
an earlier compatible release SHA for rollback through the same current control code.
The historical `personal-preview` name remains for its configured OIDC identity.

Application apply automatically disables only this product's background registrations,
requires the live controller to acknowledge their exact SSM versions, and waits up to
20 minutes for actual task termination, including STOPPING tasks. It then applies the
runtime change, refreshes the three task revisions and RunTask/PassRole grant together,
restores the preceding enabled flag, and waits for acknowledgement again. Other
products and their schedules stay enabled. Durable checkpoints under the release
bucket's `cloudformation/personal/releases/` prefix allow the same operation to resume
without repeating completed runtime or registration updates. A timeout leaves admission
paused; it never kills a user's task. Failed CloudFormation updates require investigation
or a newly reviewed compatible rollback before restoring the recorded enabled flag.

Plans bind the exact manifest bytes and control SHA, expire after 24 hours before
execution, and reject intervening runtime changes. Rollback validates manifests against
the selected commit's source files without executing that commit's control scripts.
Bootstrap supplies the exact Platform host role ARN for the registration IAM grant.
An ordinary release must preserve `BackgroundMode=admitted`. PostgreSQL, Valkey,
Account Center, Scholight and the common edge remain outside this runtime operation.
