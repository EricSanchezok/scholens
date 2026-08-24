# Scholens ECS production operations

This directory is the only production deployment package for Scholens. Production runs
in `ap-southeast-1` on the shared SanchezCloud VPC and ECS cluster. There is no EC2,
Docker Compose, RabbitMQ, Redis, Celery result-backend, or legacy-client production path.

## Architecture

Three CloudFormation stacks separate the administrator-owned execution boundary, retained
data, and replaceable runtime.

### `sanchezcloud-scholens-foundation-bootstrap`

An administrator creates this small retained stack first. It owns both CloudFormation
service roles, the ECS execution role, the four GitHub OIDC roles, the diagnostic role,
the two permissions boundaries, and the runtime CloudFormation managed policies. The
foundation service role can reconcile only the Scholens retained data plane and cannot
mutate IAM. The runtime service role can reconcile only its exact, boundary-constrained
runtime task and scheduler roles. Neither service role can modify the bootstrap stack or
its own permissions. Every bootstrap update remains a separate administrator operation.

### `sanchezcloud-scholens-foundation`

The foundation stack is created once and changed only through an infrastructure review.
It owns:

- immutable ECR repositories `sanchezcloud-scholens-web`, `-api`, and `-jobs`;
- retained KMS keys and private, versioned release, content, and diagnostic S3 buckets;
- retained SQS queues `document`, `research`, and `maintenance`, their DLQs, and the
  scheduler DLQ;
- a TLS- and RBAC-enabled Valkey 8 ElastiCache Serverless cache with a one-day snapshot
  retained from the `18:00` UTC daily snapshot;
- database, application, provider, mail, integration, and edge secrets;
- the alert SNS topic and persistent application/cache security groups.

The content bucket expires abandoned browser upload staging objects under
`uploads/` and temporary Zotero import handoff objects under `zotero-imports/`
after two days; canonical `documents/` artifacts have no expiration rule.

Retained resources use `DeletionPolicy: RetainExceptOnCreate` and
`UpdateReplacePolicy: Retain`: a failed initial creation cleans up its unused resources,
while deleting or replacing a successfully created stack retains them. Stack deletion is
never an incident rollback or cleanup method.

The restricted foundation role may create security groups only in the imported production
VPC. AWS CloudFormation cannot satisfy request-tag conditions on
`ec2:CreateSecurityGroup`, so creation is VPC-scoped and all later security-group mutations
remain restricted to resources tagged `Product=Scholens`. The role may schedule deletion
only for CloudFormation-managed Scholens KMS keys so `RetainExceptOnCreate` can complete a
failed initial-creation rollback; successfully created keys remain retained.

### `sanchezcloud-scholens-production`

Every release updates the runtime stack with digest-qualified images. It owns:

- one public IPv4 ALB with TLS, WAF, and separate Web/API target groups;
- canonical Web and FastAPI services, each with two on-demand Fargate tasks at steady
  state;
- document, research, and maintenance Celery services with one on-demand base task and
  Fargate Spot for scale-out;
- a private Cloud Map `A` record for worker callbacks, registered directly from each API
  task's `awsvpc` ENI; the ECS service registry therefore carries only the registry ARN,
  while `/internal/v1` is never on the ALB;
- an EventBridge Scheduler one-shot task for daily Zotero orchestration;
- migration and scheduler task definitions, autoscaling policies, alarms, logs, and the
  `SanchezCloud-Scholens` dashboard.

The runtime imports the existing `sanchezcloud-compute-foundation` networking and
`sanchezcloud-production` ECS cluster. It does not create a VPC, NAT gateway, database,
or cluster.

## Runtime boundaries

| Image                        | Workloads                                                         | Notes                                                                                                                                                                                                                                                                                          |
| ---------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sanchezcloud-scholens-web`  | canonical `web/` Next.js standalone server                        | Public values are baked at build time; browser source maps are removed from the image and stored privately.                                                                                                                                                                                    |
| `sanchezcloud-scholens-api`  | API, dedicated Conversation worker, and one-off product migration | The entrypoint composes escaped, driver-specific SQLAlchemy and asyncpg RDS URLs from independent secret fields, keeps credentials out of child-process arguments, and enforces `verify-full` TLS. Conversation generation uses its own ECS service and SQS queue, not an API request process. |
| `sanchezcloud-scholens-jobs` | three queue-specific workers and the one-shot scheduler           | Production uses predefined SQS URLs, no result backend, late acknowledgement, long polling, and ECS task protection.                                                                                                                                                                           |

The API runtime uses a digest-pinned Alpine Python image. The Jobs image builds its
locked dependencies on the digest-pinned Debian Python image because PyMuPDF publishes
glibc-only Linux wheels, then copies CPython and the application into a digest-pinned,
non-root distroless runtime. Both runtime images omit Perl and build toolchains; do not
replace the Jobs runtime with Alpine or add a shell solely to make its dependencies fit.

The Web image pins the standalone Next.js child process to `0.0.0.0` at container start.
Docker and ECS inject a per-container `HOSTNAME`, so a Dockerfile `ENV HOSTNAME=0.0.0.0`
alone is not a runtime guarantee. CI must start the built image and reach `/healthz` over
container loopback; otherwise ECS would repeatedly replace an externally reachable task
whose container health check cannot connect to its own server.

Every read-only, non-root Python workload mounts task-scoped ephemeral storage at `/tmp`.
A short-lived initializer from the workload's same digest runs without secrets, drops all
Linux capabilities, changes only that mounted directory to mode `01777`, and must succeed
before the workload starts. The initializer is the only root container and exits before
application code runs; do not make the long-lived API, migration, worker, or scheduler
container root merely to obtain writable temporary storage.

The pinned ADOT sidecar sends traces to X-Ray and metrics to CloudWatch. Jobs worker task
roles are queue-specific; the Conversation worker shares the API task role because it
executes the same authorized application/tool capabilities, with additional receive-only
access to the Conversation queue and ECS task protection. The execution role can pull
images and inject only the reviewed secrets. API and Conversation diagnostic snapshots
are written under `api/`, while Jobs snapshots use `workers/`; those prefixes are part of
the workload IAM contract rather than a shared unrestricted diagnostics namespace.
The shared API cache identity is limited to rate, concurrency, translation, and bounded
`scholens:conversation-events:*` replay keys. The Jobs cache identity cannot access that
Conversation namespace.

API, Conversation worker, Jobs workers, and the scheduler receive the same
private Cloud Map `WEBHOOK_BASE_URL`. Server-image job producers validate it at
process startup and reject a missing or loopback production value. Jobs-image
workloads independently validate that authority and rebase signed internal
callback paths onto it, so an accepted task cannot retain a producer-local host.
The API treats a PDF dispatch that remains unclaimed for one hour as lost,
performs one idempotent replacement while preserving memberships and quota, and
then exposes a retryable terminal failure rather than creating an unlimited
recovery chain. Every automatic replacement increments
`scholens.jobs.pdf_unclaimed_recoveries`; the production alarm pages on the
first occurrence because healthy ingestion does not use this recovery path.

The Web service accepts bounded, same-origin anonymous performance events at
`/__telemetry/web-performance`. It writes low-cardinality `web_performance` JSON to the
Web log group without user IDs, content, query strings, raw URLs, or client IPs. The
production dashboard owns p75/p95 views for navigation, Core Web Vitals,
Conversation feedback/stream milestones, durable acceptance, and worker claim age,
split by route group, device class, and `CN`/`non-CN`; Cloudflare colo remains a diagnostic
log field rather than a metric dimension.

Browser upload sessions validate and download the exact S3 object version observed by
the API. The runtime permissions boundary and API task role therefore grant
`s3:GetObjectVersion` only for the content bucket's `uploads/*` keys. Worker roles do not
receive that action because canonical `documents/*` reads use the current object.
The API receives the foundation-exported content KMS key ARN as `S3_KMS_KEY_ID` and
uses `aws:kms` with that exact key for canonical object writes; it must not override the
KMS-only bucket policy with S3-managed `AES256` encryption.
An unavailable pre-acceptance read releases the upload lease as retryable: the current
browser page retains the original `File`, while a refreshed page requires the operator to
select it again. Abandoned staging objects are not backfilled and expire after two days.

The unified `scholens doctor` command is transport-aware: production validates all three
predefined SQS queues and never probes RabbitMQ, while local AMQP development keeps its
RabbitMQ socket check.

Neither CloudFormation service role is an account administrator. The administrator-owned
foundation role has no IAM mutation actions. The runtime role may create or update only
boundary-constrained `SanchezCloudScholens*TaskRole` roles, the exact scheduler invocation
role, and the exact telemetry policy; it cannot remove a permissions boundary. Every
`iam:PassRole` is additionally bound to the exact receiving service. Runtime IAM roles
and their telemetry policy are replaceable control-plane resources and deliberately have
no retention policy; CloudFormation cleans them up on a failed create or controlled stack
deletion. Stack termination protection blocks casual deletion without preventing
CloudFormation from rolling back a failed resource create.

KMS keys, buckets, secrets, repositories, queues, schedules, topics, log groups, alarms,
dashboards, ALB/WAF resources, and runtime task families use Scholens ARNs or product/stack
tags. The runtime role's EventBridge Scheduler lifecycle is bound to the single declared
`sanchezcloud-scholens-zotero-sync` schedule. `Resource: "*"` remains only where the AWS
authorization model requires it or where a create operation has no resource ARN yet:
service/resource discovery (`Describe*`, selected `List*`, Cloud Map reads), KMS `CreateKey`
and `ListAliases`, Secrets Manager
`GetRandomPassword`, service-linked-role creation with an exact service condition,
ECS/ELB/Application Auto Scaling creation and registration, Cloud Map service creation with
a product request-tag condition, CloudWatch alarm discovery, and WAF disassociation as
required by the AWS WAF authorization model. WAF association and association reads are
limited to the account's regional Web ACL namespace, while the paired ALB actions remain
limited to the named Scholens load balancer. Creating or updating the Scholens Web ACL also
allows those two write actions against the regional managed-rule-set namespace because AWS
WAF authorizes managed rule references as part of the Web ACL request; no other WAF action
is granted on that namespace. Deployment contract tests keep broad IAM, KMS, S3, Secrets
Manager, and ECR administration from returning.

`NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_ACCOUNT_CENTER_URL` are immutable Web build-time
values recorded in the release manifest; neither is mutable ECS runtime configuration.
Set each to an absolute, credential-free HTTPS URL with no query string or fragment. A
stable path is allowed when the product endpoint requires one.

## Release contract

CI and deployment use four workflows:

1. `CI` runs the repository gates and image build tests.
2. `Publish immutable release` runs automatically only after successful `main` CI. It
   builds linux/amd64 images, emits SBOM/provenance attestations, resolves each OCI index
   to its exact runtime child, rejects any unwaived HIGH/CRITICAL ECR finding, exports the
   Web image and private source-map index from one BuildKit graph, conditionally writes
   every content-addressed map, and writes one immutable `releases/<sha>/manifest.json`.
3. `Run protected product migration` clones only the reviewed migration task definition,
   replaces its API image with the selected manifest digest, injects the exact release
   SHA, verifies that live migration history is an immutable prefix of the candidate,
   runs it once, checks the unique Scholens head and exact Identity schema proof, writes
   an immutable per-release migration attestation plus the versioned current database
   contract, and deregisters the candidate revision.
4. `Deploy immutable release` verifies the manifest against the checked-out source,
   rechecks live digest-bound ECR results and the current database contract, deploys the
   runtime stack through its CloudFormation service role, waits for all ECS services, and
   checks Web and API health through Cloudflare. Failed ECS stabilization or an external
   smoke test automatically restores the prior database-compatible immutable release or
   disables the failed candidate. Both the candidate and recovery CloudFormation package
   uploads use the foundation-exported configuration KMS key required by the release-bucket
   policy. Every external health attempt has a five-second connection timeout and a
   twenty-second total request timeout so a runner network failure cannot indefinitely
   prevent the recovery path from executing.

The release workflow keeps its verifier and orchestration scripts on the trusted workflow
`main` SHA. Candidate and rollback commits are checked out only as data in separate
directories; the current verifier reads their manifest-bound source and template without
executing old control-plane code. Template parameter overrides are intersected with the
selected immutable template. Supported parameters not explicitly changed retain the
existing stack value, so parameter additions do not make an older compatible template
undeployable.

Publishing never changes production. Deploy and rollback both select an exact 40-character
commit SHA already contained in `main`. Rollback redeploys an older immutable manifest; it
does not move tags, rebuild images, reverse a migration, or restore a database snapshot.
The selected application's migration revision must be present in the live ordered chain
and must be at or above `minimum_compatible_application_revision`. An additive migration
therefore preserves application rollback, while a reviewed contract migration deliberately
advances that floor after old application revisions can no longer run safely.

When both the current and selected releases are enabled, runtime changes use a mandatory
compatibility phase before the final switch. A forward deploy runs the candidate API and
workers behind the previous Web image, waits for every ECS service, and checks both public
health endpoints before deploying the candidate Web. A rollback reverses the order: the
selected older Web is verified against the current API and workers before those services
move back. This requires adjacent public contracts to remain bidirectionally compatible
during a rollout; the workflow does not rely on simultaneous task replacement.

ECS stability and public `/healthz` checks are necessary transport checks, not functional
proof of the Redis, versioned-S3, or asynchronous ingestion paths. After every runtime
change affecting those dependencies, an authenticated operator must:

1. send a real Conversation message and observe a terminal successful response;
2. upload a small text PDF and observe upload acceptance, document-queue consumption,
   completed Library ingestion, and a readable document;
3. confirm the document, research, and maintenance queues and DLQs drain to zero;
4. generate one harmless diagnostic response and confirm an encrypted object appears
   under `api/` without sensitive request data; and
5. confirm there are no new Redis, S3, target-5xx, or diagnostic-writer failures.

If a candidate fails ECS stabilization or the public health checks, use the automated
exact-runtime recovery path. If functional verification exposes a data-integrity or security
regression, disable the application and patch forward; do not treat a known functionally
broken prior release as the completed recovery.

The runtime template exceeds CloudFormation's inline limit. The production workflow uses
the release bucket's `cloudformation/<sha>/` prefix and explicitly encrypts each uploaded
template with the foundation configuration KMS key; relying on the AWS CLI's default
artifact encryption is rejected by the bucket policy. Release manifests remain immutable;
CloudFormation packages and source maps expire only after their 365-day compliance
retention has elapsed.

## One-time AWS setup

First deploy and drain the reviewed Scholight delegation-secret runtime change described
below. Resolve its retained secret and exact KMS key exports before creating the Scholens
bootstrap; they are required bootstrap inputs, not values to copy manually. Then use an
administrator session to create the bootstrap and use its restricted foundation service
role to create the retained data plane. Both files are below the repository's 48,000-byte
bootstrap ceiling and use CloudFormation `TemplateBody`; no unmanaged temporary bucket is
involved.

```bash
delegation_secret_arn=$(aws cloudformation list-exports \
  --region ap-southeast-1 \
  --query 'Exports[?Name==`sanchezcloud-scholight-mcp-delegation-secret-arn`].Value|[0]' \
  --output text)
delegation_kms_key_arn=$(aws cloudformation list-exports \
  --region ap-southeast-1 \
  --query 'Exports[?Name==`sanchezcloud-scholight-configuration-key-arn`].Value|[0]' \
  --output text)
avatar_kms_key_arn=$(aws cloudformation describe-stacks \
  --region ap-southeast-1 \
  --stack-name sanchezcloud-account-center-foundation \
  --query 'Stacks[0].Outputs[?OutputKey==`AvatarKmsKeyArn`].OutputValue|[0]' \
  --output text)
test "$delegation_secret_arn" != None
test "$delegation_kms_key_arn" != None
test "$avatar_kms_key_arn" != None

aws cloudformation validate-template \
  --region ap-southeast-1 \
  --template-body file://deploy/ecs/scholens-foundation-bootstrap.yml

aws cloudformation deploy \
  --region ap-southeast-1 \
  --stack-name sanchezcloud-scholens-foundation-bootstrap \
  --template-file deploy/ecs/scholens-foundation-bootstrap.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOidcProviderArn=<provider-arn> \
    RdsSecurityGroupId=<shared-rds-security-group-id> \
    ScholightMcpDelegationSecretArn="$delegation_secret_arn" \
    ScholightMcpDelegationKmsKeyArn="$delegation_kms_key_arn" \
    AvatarKmsKeyArn="$avatar_kms_key_arn" \
  --tags \
    System=SanchezCloud \
    Product=Scholens \
    Environment=production \
    ManagedBy=CloudFormation

foundation_role_arn=$(aws cloudformation list-exports \
  --region ap-southeast-1 \
  --query 'Exports[?Name==`sanchezcloud-scholens-foundation-cloudformation-role-arn`].Value|[0]' \
  --output text)
test "$foundation_role_arn" != None

aws cloudformation validate-template \
  --region ap-southeast-1 \
  --template-body file://deploy/ecs/scholens-foundation.yml

aws cloudformation deploy \
  --region ap-southeast-1 \
  --stack-name sanchezcloud-scholens-foundation \
  --template-file deploy/ecs/scholens-foundation.yml \
  --role-arn "$foundation_role_arn" \
  --tags \
    System=SanchezCloud \
    Product=Scholens \
    Environment=production \
    ManagedBy=CloudFormation \
  --parameter-overrides \
    ProductionDomain=scholens.sanchezcloud.net \
    AlertEmail=<operator-email>
```

The bootstrap deployment intentionally has no `--role-arn`: it is the administrator-owned
IAM security plane. The foundation deployment always uses the exported restricted role and
therefore fails closed if its template tries to mutate IAM. Standard resource tags are
inherited from the four stack tags above; the protected foundation workflow supplies the
same tags on later data-plane updates. Any role, managed-policy, permissions-boundary, or
bootstrap permission change requires a separately reviewed administrator update.
The Account Center avatar key is deliberately not a cross-stack export. Bootstrap and
runtime deployment resolve the exact `AvatarKmsKeyArn` output from the retained
`sanchezcloud-account-center-foundation` stack and pass it as an ARN-validated parameter;
neither policy may fall back to an account-wide KMS wildcard.
Deploy a reviewed bootstrap permissions-boundary update before a runtime template that
depends on its new action. In particular, the scoped `s3:GetObjectVersion` boundary must
be active before deploying the API role policy that performs version-locked staged-upload
reads; verify the managed policy's default version before starting the runtime release.
Every later runtime release also simulates the live API role's `s3:GetObject` and
`kms:Decrypt` decisions for the shared avatar prefix and key. The release fails closed
unless both the role policy and its permissions boundary allow the exact dependency with
the required KMS context. Therefore the administrator-owned bootstrap must be updated
before a release that introduces or changes shared-avatar access; a committed template or
runtime stack parameter alone is not accepted as proof of the effective permission.
The restricted role scopes the serverless-cache ARN to the canonical
`sanchezcloud-scholens` name and includes both create and rollback deletion for each
CloudFormation-managed bucket policy; keep those lifecycle permissions symmetric when the
foundation adds a retained resource. ElastiCache Serverless also requires EC2 dependent
actions for its managed interface endpoint; those actions are restricted to the imported
production VPC, its two private subnets, the Scholens security group, and endpoint tagging
during `CreateVpcEndpoint`.
The runtime role likewise grants CloudWatch alarm lifecycle actions to the Scholens alarm
prefix plus the single exact shared-RDS capacity alarm owned by the runtime stack; create
and rollback-delete permissions must remain symmetric for that exception.

Confirm the SNS email subscription. Later foundation changes use the protected
`Update production foundation` workflow; `plan` creates, describes, and deletes a change
set, while `apply` executes a reviewed update through the stack service role.

Request the ACM certificate in `ap-southeast-1`, create its DNS validation CNAME in
Cloudflare, and wait for `ISSUED`. The runtime stack accepts only the certificate ARN; it
does not own DNS.

## Secrets and database roles

CloudFormation generates the database, cache, core, and edge secret containers and their
initial random values. It creates the AI, mail, and integration containers with no value at
all, so later foundation changes cannot reset operator-owned provider credentials.
CloudFormation never creates PostgreSQL roles. Never copy production secret values into
GitHub.

Required secret groups are:

- `/sanchezcloud/database/scholens-runtime` and `-migrator`;
- `/sanchezcloud/scholens/production/core`;
- `/sanchezcloud/scholens/production/cache-api` and `cache-jobs`;
- `/sanchezcloud/scholens/production/ai`;
- `/sanchezcloud/scholens/production/mail`;
- `/sanchezcloud/scholens/production/integrations`;
- `/sanchezcloud/scholens/production/edge`.

Before the first runtime deployment, use an administrator session to write complete new
versions for the operator-managed containers and to replace the empty generated core
fields. Generate independent values for every JWT, HMAC, session, cursor, encryption,
callback, and origin token. Required JSON keys are:

- core: `auth_jwt_secret`, `admin_session_secret`, `paper_search_cursor_secret`,
  `project_invitation_token_secret`, `jobs_webhook_signing_secret`,
  `integration_credential_encryption_key`;
- AI: `deepseek_api_key`, `moss_api_key`, `moss_voice_id`;
- mail: `aliyun_access_key_id`, `aliyun_access_key_secret`,
  `aliyun_account_name`;
- integrations: `zotero_client_key`, `zotero_client_secret`.

`CoreSecret.GenerateSecretString` is only the frozen first-stack seed and deliberately
does not enumerate keys added after the foundation was first created. Never add a new
runtime key to that CloudFormation property: changing it creates a new secret version and
can replace the operator-owned `AWSCURRENT` value. Add or rotate core keys by reading the
current JSON, writing one complete reviewed secret version, and then running the shape
check below. Provider containers are empty CloudFormation resources for the same reason.

Run this read-only preflight for each secret after writing its reviewed version (replace
the sample key array for that container); it rejects missing, non-string, and empty values:

```bash
secret_json=$(aws secretsmanager get-secret-value \
  --secret-id /sanchezcloud/scholens/production/ai \
  --query SecretString --output text)
jq -e --argjson required \
  '["deepseek_api_key","moss_api_key","moss_voice_id"]' \
  '. as $doc | all($required[]; . as $key | ($doc[$key] | type == "string" and length > 0))' \
  <<<"$secret_json"
```

Repeat the same shape check for core, mail, and integrations. The generated
database secrets must contain non-empty `host`, `port`, `dbname`, `username`, and
`password`; cache secrets must contain non-empty `username` and `password`; the edge
secret must contain a non-empty `origin_token`. ECS injects individual JSON fields and
will not start with an absent key, so this preflight is a first-release gate. The shared
Scholight delegation secret is imported read-only from Scholight's foundation and is not
copied into a Scholens secret.

The deploy workflow takes the current and previous edge-secret version IDs explicitly.
Resolve them without reading or printing the secret value:

```bash
EDGE_SECRET_ID=/sanchezcloud/scholens/production/edge
EDGE_CURRENT_VERSION_ID=$(aws secretsmanager list-secret-version-ids \
  --secret-id "$EDGE_SECRET_ID" \
  --query 'Versions[?contains(VersionStages, `AWSCURRENT`)].VersionId | [0]' \
  --output text)
EDGE_PREVIOUS_VERSION_ID=$(aws secretsmanager list-secret-version-ids \
  --secret-id "$EDGE_SECRET_ID" \
  --query 'Versions[?contains(VersionStages, `AWSPREVIOUS`)].VersionId | [0]' \
  --output text)
if [[ -z "$EDGE_PREVIOUS_VERSION_ID" || "$EDGE_PREVIOUS_VERSION_ID" == None ]]; then
  EDGE_PREVIOUS_VERSION_ID=$EDGE_CURRENT_VERSION_ID
fi
```

An absent `AWSPREVIOUS` is normal when no rotation is active; pass the current ID for both
workflow inputs. During rotation, first create the new secret version, configure Cloudflare
to send the new token, and deploy with the new and old version IDs. After propagation is
verified, deploy again with the new ID in both inputs; only then retire the old version.
The workflow role never reads the origin token.

The cross-product migration order is strict: deploy the Scholight foundation to create
and export the retained delegation secret and its exact configuration-key ARN; deploy
the Scholight runtime task definition so API tasks read that new secret; then create the
Scholens foundation and deploy Scholens runtime using those same exports. The new secret
generates a new value, so no operator copies the old core-secret value. Because delegation
tokens are short-lived, a coordinated runtime switch is sufficient. Keep the old
`mcp_delegation_jwt_secret` field in Scholight core during this sequence; remove that
field only after the new Scholight runtime is healthy, all old API tasks have drained,
and no task definition or execution-role injection references it.

Create the existing-login roles `scholens_app` and `scholens_migrator` in RDS with
passwords exactly matching the generated database secrets. `auth_migrator` remains owned
by SanchezCloud Identity. Run `database-bootstrap.sql` as the database owner before the
Identity migration, after the Identity migration, and after the Scholens migration. It is
idempotent, installs the reviewed `pg_trgm` and `vector` extensions in `public`, and keeps
`auth` and `scholens` ownership separate. RDS must expose both extensions before the
hybrid-search expand migration runs. The runtime role cannot run DDL; the product migrator
cannot modify `auth.*`.

The API runtime is the sole Scholens workload allowed to read shared avatars. Its
database extension is exactly `SELECT` on `auth.user_avatars`; its object access is
exactly `s3:GetObject` below the retained Account Center bucket's
`auth/avatars/v1/*` prefix; and KMS decrypt is constrained by S3 service and that
encryption context. Workers, schedulers, migration tasks, and the browser receive no
avatar bucket or key permission. `SHARED_AVATAR_BUCKET` is derived from the retained
account bucket name and the API signs 15-minute GET views; CloudFormation never creates,
writes, deletes, or deploys that shared resource from Scholens.

## GitHub environments

Create four protected environments. Configure deployment branches so every environment
allows only the `main` branch and must not allow tags, arbitrary branches, or an
"all branches" policy. `production`, `database-production`, and
`infrastructure-production` require distinct reviewer rules; keep `image-publish`
restricted to `main` even if it does not require a human approval.

| Environment                 | Variables                                                                                                                                                                                          |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `image-publish`             | `AWS_REGION`, `AWS_PUBLISH_ROLE_ARN`, `IDENTITY_READER_APP_ID`, `PRODUCTION_API_URL`, `ACCOUNT_CENTER_URL`                                                                                         |
| `database-production`       | `AWS_REGION`, `AWS_DATABASE_ROLE_ARN`                                                                                                                                                              |
| `production`                | `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `AWS_RUNTIME_CLOUDFORMATION_ROLE_ARN`, `PRODUCTION_DOMAIN`, `PRODUCTION_API_URL`, `ACCOUNT_CENTER_URL`, `PRODUCTION_CERTIFICATE_ARN`, `RDS_SECURITY_GROUP_ID` |
| `infrastructure-production` | `AWS_REGION`, `AWS_INFRASTRUCTURE_ROLE_ARN`, `AWS_FOUNDATION_CLOUDFORMATION_ROLE_ARN`, `AWS_GITHUB_OIDC_PROVIDER_ARN`, `PRODUCTION_DOMAIN`, `ALERT_EMAIL`                                          |

`IDENTITY_READER_PRIVATE_KEY` is the only repository dependency-reader secret. AWS access
uses OIDC; there are no long-lived AWS access keys in GitHub.

## Cloudflare boundary

Create a proxied CNAME for `scholens.sanchezcloud.net` pointing to the runtime stack's
`LoadBalancerDnsName`. Configure Cloudflare to send `x-scholens-origin` with the
`origin_token` value from the edge secret. Do not expose that value to browser code.

Use Full (strict) TLS, preserve the `Host` header, and keep proxying enabled. On the
ordinary proxied request path Cloudflare generates the single
[`CF-Connecting-IP`](https://developers.cloudflare.com/fundamentals/reference/http-headers/#cf-connecting-ip)
value sent to the origin;
[Request Header Transform Rules](https://developers.cloudflare.com/rules/transform/request-header-modification/#important-remarks)
cannot set that header and must not remove it. Do not attach a Worker or Snippet that can
derive it from mutable `x-real-ip`; keep Pseudo IPv4 disabled unless its deliberate
IPv6-loss tradeoff is separately
reviewed. The application disables Uvicorn proxy-header rewriting, verifies the raw peer
against the imported production VPC CIDR, then uses that canonical
`CF-Connecting-IP` value for request logs and all application rate limits. Missing,
repeated, malformed, or untrusted headers fail closed.

Keep Cloudflare Bot Fight Mode disabled for this zone. It cannot be scoped away from the
public API or release health endpoints and may challenge legitimate API clients and hosted
monitoring runners. Cloudflare documents that this mode runs outside the Ruleset Engine and
cannot be bypassed with WAF custom rules; the AWS WAF controls below remain the adjustable
application-security boundary.

The WAF blocks requests that bypass Cloudflare or omit the origin header, then applies AWS
managed common-threat/IP-reputation rules and a `CF-Connecting-IP` rate limit. The
common-threat rule set is split by path into two scopes:

- Structured paths (auth, billing, access keys, invitations, tags, integration
  credentials, and every other body-bearing route not listed below) keep the full CRS
  inspection, including all five body rules.
- Free-text content paths are matched by `LargeBodyPathSet` (`/mcp`,
  `conversations`, `paper-ingestions`) plus `ContentFreeTextPathSet` (selection
  translation, annotation threads/comments, library paper metadata, translation
  preferences, projects, onboarding, audio-overview instructions, search). On these
  paths the five CRS body rules (`SizeRestrictions_BODY`,
  `EC2MetaDataSSRF_BODY`, `GenericLFI_BODY`, `GenericRFI_BODY`,
  `CrossSiteScripting_BODY`) run in Count mode, so legitimate academic text containing
  path-like strings is logged and metered instead of blocked. Query-string inspection
  remains enforced because these APIs carry their free text in request bodies. Academic
  text legitimately contains `../`-style tokens, so full body
  content inspection on those routes is a false-positive source, not protection; the
  application layer still enforces field length caps, JSON parsing, auth, and per-module
  authorization, and the origin/IP-reputation/rate-limit rules remain unchanged.

Every body-bearing public write route must be explicitly classified by
`test_waf_free_text_path_sets_classify_every_public_write_route` in
`server/tests/test_deployment_contract.py`: it either matches one of the two path sets
or appears in the structured whitelist. A new or renamed route that lands in neither
bucket fails the deployment gate, which is the WAF classification obligation for the
change that introduces it.

WAF Block and Count records stream to the `aws-waf-logs-scholens-production` CloudWatch
Logs log group (30-day retention); ordinary allowed traffic is dropped by the logging
filter. The `x-scholens-origin`, `cookie`, and `authorization` headers are redacted and
request bodies are substituted by the Web ACL data-protection policy. Sampled requests
remain disabled on the entire Web ACL and every rule because normal requests carry the
origin secret; aggregated CloudWatch metrics remain enabled. During origin-token
rotation, check WAF/CloudTrail access history for
unexpected prior visibility before retiring the old version. Verify that the ALB DNS
name fails without the header and the public hostname succeeds through Cloudflare.

The first runtime release that enables WAF logging depends on the reviewed
`RuntimeOperationsPolicy` logging actions in
`scholens-foundation-bootstrap.yml`. An administrator must deploy that bootstrap update
before the runtime release; the restricted foundation workflow cannot reconcile IAM.
The release workflow prints the terminal CloudFormation resource events when a runtime
update fails so a missing bootstrap prerequisite is distinguishable from ECS health or
application failure.

## Initial production bootstrap

This sequence records how the retained production resources were first created. It is not
the normal release procedure and must not be replayed against an existing production
stack.

1. Merge the reviewed release implementation into `main` and let CI pass.
2. Create the administrator-owned bootstrap and foundation stacks in the documented order,
   confirm SNS, fill all required secrets, create database roles/grants, and validate the
   ACM certificate.
3. Configure the four GitHub environments. Prepare and review the Cloudflare origin-header
   rule and Managed Transform, but do not point the production CNAME before the disabled
   runtime stack exposes its ALB hostname.
4. Let `Publish immutable release` create the first manifest.
5. Run `Deploy immutable release` for that SHA with `ApplicationEnabled=false` and
   `SchedulerState=DISABLED`, supplying the reviewed edge-secret version IDs. This creates
   the reviewed migration task while every service remains at zero.
6. Run `Run protected product migration` for the same SHA, then rerun
   `database-bootstrap.sql` as the database owner to refresh runtime grants.
7. Point the proxied Cloudflare CNAME at the disabled runtime's `LoadBalancerDnsName`,
   enable the reviewed origin-header rule and Managed Transform, confirm DNS is proxied,
   and verify direct ALB requests without the origin header are denied. Services remain at
   zero during this boundary change, so do not expect the public health endpoints to pass
   yet.
8. Deploy the same SHA with `ApplicationEnabled=true`, still with the scheduler disabled.
   The release workflow immediately requires both public Cloudflare health checks to pass;
   then verify authentication, upload, document, research, callback, queue-drain,
   billing usage, private entitlement grants, Zotero, source-map, alarm, and
   autoscaling paths. Checkout, subscription mutation, Stripe webhook, and
   PostHog remain intentionally absent from the current production release.
9. Enable the scheduler only after the one-shot job and maintenance queue are verified.

## Subsequent releases and migrations

Ordinary changes merge through review and CI, after which the publish workflow may create
an immutable manifest. Publishing alone never changes production. An authorized operator
then runs the protected migration workflow when the release contains a new revision and
deploys only after its attestation becomes current.

A release that changes runtime grants in `database-bootstrap.sql`, including a
grant-only release with no schema revision, requires the database owner to apply that
file idempotently before the protected migration workflow. The migration task audits
that `scholens_app` has `SELECT` and no write privilege on
`auth.user_avatars` before it emits an attestation; missing or over-broad access therefore
blocks deployment instead of surfacing later as a fail-soft avatar fallback.

Every new migration is appended to the linear history and classified in
`server/migrations/policy.json`. The protected migration workflow rejects a candidate when
the live history is not its exact prefix, when any applied migration checksum changed, or
when the compatibility floor moves backward. The first version 3 manifest establishes
revision `c9f4a62d01ab` as the production baseline without changing schema; later expand
revisions retain the existing floor. A contract revision may advance the floor only after
the backfill, drain, recovery, and supported-application evidence required by
[`docs/architecture/contract-evolution.md`](../../docs/architecture/contract-evolution.md)
has been reviewed.

Never use Alembic downgrade as production application rollback. A migration failure is
repaired by a forward revision or an explicitly approved database recovery operation.

## Capacity and failure handling

- Web scales 2–6 and API scales 2–3 on CPU, memory, and ALB request targets.
- API is capped at three tasks for the shared RDS budget; each of its two Gunicorn workers
  uses a two-connection pool with one overflow slot. The shared RDS connection alarm is a
  separate early-warning gate, not permission to exceed that task cap.
- The Scholens API ceiling is therefore `3 tasks × 2 workers × (3 product + 2 Identity)` =
  30 connections. Reserve no more than 36 connections for Scholens and budget every other
  product sharing `sanchezcloud-pg` separately below the instance limit. Increase the task
  cap or either pool only after a reviewed move to a larger Multi-AZ instance or RDS Proxy,
  with a new aggregate connection budget and alarm threshold.
- The inherited shared database is currently `db.t4g.micro`, publicly accessible, and
  single-AZ. Scholens does not mutate it. Every release review must verify its security
  group admits only the application/migrator groups and that the client remains
  `sslmode=verify-full`. Before adopting a production SLA, the platform owner must review
  capacity and upgrade it to Multi-AZ; public accessibility must also receive a separate
  platform security review.
- Workers scale on SQS backlog per running task. The on-demand Conversation service keeps
  two tasks warm, scales 2–6 with concurrency one, and targets no more than 0.25 visible
  messages per running task. It uses a 60-minute queue visibility timeout and protects its
  ECS task while generation is active so browser detachment and ordinary deployments do
  not terminate accepted work. Scale-out has a 30-second cooldown; scale-in waits 15
  minutes. Jobs workers retain their 45-minute visibility and use Fargate Spot only for
  scale-out.
- Queue DLQs, oldest-message age, ALB-generated 5xx, API target 5xx, Redis/S3 dependency
  failures, shared-avatar read failures, diagnostic snapshot write failures, and unhealthy
  target alarms publish to the Scholens SNS topic. The dependency and diagnostic alarms use the
  `Scholens/Production` OpenTelemetry metrics and fire on the first failure in five
  minutes; the API target alarm fires at five responses in five minutes. Production
  application exporters send Counter and Histogram instruments with delta temporality so
  CloudWatch `Sum` evaluates each window rather than a process-lifetime cumulative value.
  The interactive Conversation queue alarm treats an oldest visible message of 15 seconds
  as a latency incident and evaluates the next available one-minute SQS metric immediately;
  the 60-second AWS/SQS publication period is the detection floor, not the tolerated queue
  age. Server OpenTelemetry histograms and browser Conversation RUM provide the finer-grained
  accept, publish, claim, and first-content phase breakdown; the deployment does not invent
  a higher-resolution SQS metric contract.
- ECS services use deployment circuit-breaker rollback. A failed database task does not
  change application services. A candidate that fails deployment, ECS stabilization, or an
  external smoke check enters automatic recovery and remains a failed release after
  recovery. If a forward release reached its final Web phase, recovery retains the already
  compatibility-tested candidate API and workers while restoring the previous Web image;
  this keeps already-loaded candidate browser tabs valid. A compatibility-phase failure or
  rollback failure restores the exact previous template parameters and image set, including
  a prior compatibility state that spans two immutable manifests.
- If the first disabled runtime create leaves `CREATE_FAILED`, `ROLLBACK_COMPLETE`, or
  another incomplete-create status, the release workflow refuses to treat it as a prior
  deployment. An administrator must inspect the stack events and manually delete that
  never-enabled stack, whose termination protection was not enabled, before retrying the
  disabled bootstrap. The GitHub role intentionally has no `DeleteStack` permission.
- Never delete a retained resource, release manifest, or digest during incident response.

Local verification is side-effect free:

```bash
./scripts/run-gates.sh deployment
```

That lane lints all three templates, rejects YAML aliases unsupported by CloudFormation, and
runs the deployment, manifest, and runtime-entrypoint contract tests. AWS API validation
is performed separately with an authenticated operator session.
