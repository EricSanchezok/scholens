# Personal-account ECS deployment

This is the isolated migration target. The existing Singapore Fargate package and
release workflows remain available until a separately approved production cutover.
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

The personal renderer disables all Scholens email delivery explicitly. This suppresses
both identity email senders and the project-invitation delivery supervisor, even if
credentials are accidentally present. Managed deployments retain the enabled default.


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
