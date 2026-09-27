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
short product outage to avoid static-port conflicts and doubled memory use.

The API receives 512 CPU shares and the inference owner 16. These are relative
weights, not hard CPU quotas: an otherwise idle host can still compute at full
speed, while foreground requests win contention with sustained indexing. ECS
also schedules each task through a parent cgroup; inspect that parent's actual
`cpu.weight` when validating placement, because changing only a single container
inside its task does not establish priority across tasks. Memory ceilings and
admission reserves remain independent. The controller must still verify remaining
ECS CPU and physical memory before every background launch; shares do not grant
capacity to exceed either placement budget.

The API and conversation worker have 1,536 MiB hard limits so local semantic
embedding initialization fits alongside application imports. The document
worker now has a 1,280 MiB hard limit and a 512 MiB reservation. Its former
2,560 MiB limit covered a second in-process model and prevented admission on the
shared host. With the required shared inference owner,
application processes use a private Unix socket instead of loading ONNX weights.
The single inference owner uses the same API image, one compute thread, one-text
microbatches and a 1,024 MiB hard limit. It has no task role, secrets, TCP ports or
external network. Its model is warmed before the socket health check succeeds.
A host directory owned by `1000:1000`, mode `0770`, holds the `0660` socket; Jobs
uses its existing non-root UID with group `1000` and a read-only mount. The owner
stops before replacement and holds an exclusive file lock before model loading.
Client failure never starts a second model: queries can degrade to lexical search
while deterministic indexing retries.

The reviewed native ARM64 fixture measured a 761 MiB peak with the pinned INT8
model, within the 1,024 MiB ceiling after 25% headroom and rounding. The current ARM64 Jobs image also completed a network-isolated, 0.75-CPU fixture:
a 29,400,304-byte / 50-page electronic PDF peaked at 742.25 MiB across parent and
parser children; analysis plus both local parser engines and imports finished in
75.89 seconds. A separate 9,000-passage checkpoint/serialization fixture peaked
at 709.21 MiB (model computation measured separately). These support the 1,280 MiB
parser and 1,024 MiB index caps with headroom. They do not prove every input or
end-to-end online latency. API/conversation caps remain 1,536 MiB pending online
measurements. No host resize is involved. The template prevents starting this
release's tokenizer-only workers without the shared inference owner.

The maintenance worker reserves 256 MiB with a 512 MiB hard limit: the shared Jobs
imports exceed the original 256 MiB limit before it can consume a task. Every
personal Celery worker reports a local heartbeat and has an explicit ECS health
check, so Conversation does not inherit the API image's HTTP probe. Queue age and
failed tasks remain separate operational signals from event-loop liveness.

`ApplicationEnabled` defaults to false for a new installation. Production is already
enabled. Ordinary releases preserve its reviewed authentication, email and endpoint
configuration. `ScholightMcpUrl` points to the unchanged public Scholight API, whose
lean service and shared database now also run in the personal account.

For an isolated recovery rehearsal, provision database/cache TLS, restore and reconcile
data, inject independent authentication secrets, keep email delivery disabled, and
verify every endpoint and queue belongs to that rehearsal before enabling services.
Restoring a database does not authorize replaying copied jobs. Record actual restore,
ARM64 startup and functional verification results separately from template generation.

## Manual ARM64 image publication

`personal-publish.yml` accepts only a revision already merged into main, runs the shared
CI workflow, and uses the `personal-image-publish` environment. Configure its AWS account,
region, publishing role, production API URL and Account Center URL from the reviewed stack
outputs. The existing repository Identity reader key is passed as a BuildKit secret.

The job runs on native ARM64, overrides both Web bake targets to ARM64, imports native
Python dependencies in the resulting images, and scans the ARM64 child digest of each
OCI index. The existing release manifest format records `linux/arm64` in each image scan;
all components must agree. The legacy CLI default is `linux/amd64`; production
verification requires explicit `--expected-platform linux/arm64`.
Publishing creates no GitHub Release, version tag, runtime deployment or database write.

The personal publisher selects `arm64-int8` for both Python images. Jobs packages
only the digest-verified tokenizer; the API image carries the registered model
artifact for the independent owner. Native image smoke tests execute that model
offline and assert that Jobs has no model weight file. Control planning enables
shared inference when the selected immutable source contains its owner module.
Ordinary rollback rejects older images without that module after shared inference
has been enabled; a legacy rollback requires a separate complete stage drain and
restoration of the prior topology. Compatible newer releases retain the socket contract.

The personal renderer defaults `EmailDeliveryEnabled` to `false`. This suppresses
both identity email senders and the project-invitation delivery supervisor, even if
credentials are accidentally present. Enable it only after reviewing the production
sender credentials and pending invitations. Ordinary releases preserve the deployed
value; isolated rehearsals keep it disabled.

Production uses its public `DomainName` and the production `PRODUCTION_API_URL` and
`ACCOUNT_CENTER_URL` in `personal-image-publish`. Web embeds these URLs at build time;
a rehearsal manifest cannot change them at deployment. The retained `personal-*`
environments and `preview` queue, secret, bucket and log names identify production
resources; their historical names do not imply an isolated test environment.

Old-account workflows are archived under `deploy/legacy/workflows` and are not release
or rollback entrypoints. Roll back through a compatible manifest in the personal
account. Retired old runtime resources require reconstruction from a verified recovery
backup; changing DNS cannot restore them. Shared production database data is never
rolled back as part of an application release.


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
workflow creates a GitHub Release or targets the retired account.

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

Deploy `application-monitoring.yml` as `scholens-personal-application-monitoring`
after the runtime log groups exist, passing the confirmed shared alert topic as
`AlertTopicArn`. Create and review its exact CloudFormation change set before
execution. It owns application log metric filters and alarms in
`Scholens/Personal`, without exporter containers. The runtime retains logs for
30 days. Metric filters and alarms have CloudWatch charges. The
[observability runbook](../../docs/operations/AWS_OBSERVABILITY_SETUP.md) owns
the signal inventory, bounded queue dimensions, actual-ingestion verification
and limitations. Deploy and verify the durable-backlog reporter before enabling
its snapshot-silence alarm. Before rolling back to an application without that
reporter, remove the reporter-dependent alarms through a reviewed monitoring
change set as described in that runbook.
Rollback of this monitoring stack does not change application tasks or stored
data; application rollback does not require removing additive filters.

Deploy `queue-monitoring.yml` once for each conversation, document, document-index,
document-enrichment, research, and
maintenance queue, supplying its queue/DLQ names from the destination foundation and
the confirmed shared alert topic from Platform. Each pair adds two standard alarms:
a visible message older than the configured waiting budget for three minutes, and any
visible dead-letter message. Missing idle SQS metrics are non-breaching. The default
waiting budget is 30 minutes for serial background work; use 60 seconds for conversation.
These alerts report delay/failure and never scale instances or replay failed work.

## Admitted background workers

[ADR 0054](../../docs/decisions/0054-admitted-background-workers.md) owns the worker
lifecycle. `BackgroundMode=resident` preserves the previous deployment. The reviewed
`admitted` mode scales document/document-index/document-enrichment/research/maintenance services to zero and enables
one-shot task definitions with explicit container hard memory bounds and soft placement reservations.
Background CPU shares may use idle host CPU; the document embedder uses one thread. Deploy
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
runtime change, refreshes the five task revisions and RunTask/PassRole grant together,
restores the preceding enabled flag, and waits for acknowledgement again. Other
products and their schedules stay enabled. Durable checkpoints under the release
bucket's `cloudformation/personal/releases/` prefix allow the same operation to resume
without repeating completed runtime or registration updates. A timeout leaves admission
paused; it never kills a user's task. Failed CloudFormation updates require investigation
or a newly reviewed compatible rollback before restoring the recorded enabled flag.

The first independent-stage rollout expands the retained foundation with two queues
and DLQs, then the bootstrap role allowlists with the two exact worker roles and SSM
parameter ARNs. Do this before deploying the application. The renderer derives stage
task definitions from the canonical document worker, but gives each a separate role,
log group, single-queue command and bounded lifecycle. Index and enrichment each have
a 1,024 MiB container ceiling (1,088 MiB including initialization), subject to measured
mixed-load acceptance before producer activation. No instance or managed compute is added.

Release coordination acknowledges the existing three registrations before the first
drain. After the runtime converges, it expands `background.yml` while disabled, adding
only the two owned registrations. Subsequent releases update all five. Each registration's
memory parameter must equal the actual sum of its task's container hard limits;
RunTask/PassRole permissions and revisions change in the same CloudFormation update.
Activate the staged producer only after five-registration acknowledgement and queue
monitoring are verified. Rollback must first stop new-stage production and finish all
accepted stage work; do not pair pending new tasks with an image that cannot execute them.

`personal-preview.yml` exposes `processing_rollout=preserve|0|10|50|100`. The first
consumer-capable release enables the receipt supervisor, shared inference and fair
publication with zero new-stage producers. Advance the stable requester cohort
through 10%, 50% and 100% only after each acceptance interval. `0` pauses producers
while retaining all consumers for accepted work. `preserve` retains the live cohort;
no ordinary release silently increases it. The template rejects stage producers
without durable receipt consumers and shared inference.

Plans bind the exact manifest bytes and control SHA, expire after 24 hours before
execution, and reject intervening runtime changes. Rollback validates manifests against
the selected commit's source files without executing that commit's control scripts.
Bootstrap supplies the exact Platform host role ARN for the registration IAM grant.
An ordinary release must preserve `BackgroundMode=admitted`. PostgreSQL, Valkey,
Account Center, Scholight and the common edge remain outside this runtime operation.

### Independent user and batch lanes

Scholens document/research/maintenance registrations select Platform's `interactive`
lane. Platform must first deploy the additive lane/resource contract with total
concurrency one. Its later reviewed concurrency-two change permits Scholight batch
work to run alongside a Scholens task. Index/enrichment follow-up work uses the
`batch` lane at priority zero so a long index does not occupy the import lane;
automatic batch/backup workloads retain their bounded aging opportunities. All
priorities satisfy Platform's 0/1 registration contract. Worker hard limits are
1,280/1,024/1,024/768/512 MiB for document/index/enrichment/research/maintenance,
plus the 64 MiB initializer. Omit task-level memory and CPU so ECS placement uses
explicit soft reservations and CPU shares. Platform also reserves at least 1 GiB
free, default 512 MiB resident growth, and active tasks' remaining hard-bound
growth before starting another task.
Release validation derives the hard total from all containers and rejects missing
bounds. No database, queue or job-envelope migration is involved.

Document workers accept at most five jobs or five minutes of new deliveries per
launch, finishing the current delivery before exit. This reduces cold starts while
retaining lane fairness and parent-side broker settlement. Update the document
queue monitoring stack's `MaximumWaitSeconds` to 120; its three-minute evaluation
window and dead-letter alarm remain unchanged. A 120-second pickup objective assumes
an empty healthy interactive lane, not an existing same-product backlog.

Rollback first sets Platform concurrency to one and reconciles all active tasks;
then drain this product before restoring task definitions. Never restore the old
single-intent controller over the new controller's multi-lane state. Do not purge,
receive for inspection, or recreate production queues during this transition.
