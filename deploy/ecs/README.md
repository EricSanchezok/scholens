# Scholens ECS production operations

This directory is the only production deployment package for Scholens. Production runs
in `ap-southeast-1` on the shared SanchezCloud VPC and ECS cluster. There is no EC2,
Docker Compose, RabbitMQ, Redis, Celery result-backend, or legacy-client production path.

## Architecture

Two CloudFormation stacks deliberately separate retained data from replaceable runtime.

### `sanchezcloud-scholens-foundation`

The foundation stack is created once and changed only through an infrastructure review.
It owns:

- immutable ECR repositories `sanchezcloud-scholens-web`, `-api`, and `-jobs`;
- retained KMS keys and private, versioned release, content, and diagnostic S3 buckets;
- retained SQS queues `document`, `research`, and `maintenance`, their DLQs, and the
  scheduler DLQ;
- a TLS- and RBAC-enabled Valkey 8 ElastiCache Serverless cache;
- database, application, provider, mail, billing, integration, and edge secrets;
- the alert SNS topic, persistent application/cache security groups, ECS execution role,
  CloudFormation service role, and scoped GitHub OIDC roles.

Retained resources have both `DeletionPolicy: Retain` and
`UpdateReplacePolicy: Retain`. Deleting the stack is never a rollback or cleanup method.

### `sanchezcloud-scholens-production`

Every release updates the runtime stack with digest-qualified images. It owns:

- one dual-stack public ALB with TLS, WAF, and separate Web/API target groups;
- canonical Web and FastAPI services, each with two on-demand Fargate tasks at steady
  state;
- document, research, and maintenance Celery services with one on-demand base task and
  Fargate Spot for scale-out;
- a private Cloud Map name for worker callbacks; `/internal/v1` is never on the ALB;
- an EventBridge Scheduler one-shot task for daily Zotero orchestration;
- migration and scheduler task definitions, autoscaling policies, alarms, logs, and the
  `SanchezCloud-Scholens` dashboard.

The runtime imports the existing `sanchezcloud-compute-foundation` networking and
`sanchezcloud-production` ECS cluster. It does not create a VPC, NAT gateway, database,
or cluster.

## Runtime boundaries

| Image | Workloads | Notes |
| --- | --- | --- |
| `sanchezcloud-scholens-web` | canonical `web/` Next.js standalone server | Public values are baked at build time; browser source maps are removed from the image and stored privately. |
| `sanchezcloud-scholens-api` | API and one-off product migration | The entrypoint composes an escaped RDS URL from independent secret fields and enforces `verify-full` TLS. |
| `sanchezcloud-scholens-jobs` | three queue-specific workers and the one-shot scheduler | Production uses predefined SQS URLs, no result backend, late acknowledgement, long polling, and ECS task protection. |

The pinned ADOT sidecar sends traces to X-Ray and metrics to CloudWatch. Application and
worker task roles are separate; the execution role can pull images and inject only the
reviewed secrets.

The CloudFormation service role is not an account administrator. IAM access is restricted
to `SanchezCloudScholens*` roles and `iam:PassRole` is additionally bound to the exact
receiving service. KMS keys, buckets, secrets, repositories, queues, schedules, topics,
log groups, alarms, dashboards, ALB/WAF resources, and runtime task families use Scholens
ARNs or product/stack tags. `Resource: "*"` remains only where the AWS authorization model
requires it or where a create operation has no resource ARN yet: service/resource discovery
(`Describe*`, selected `List*`, Cloud Map reads), KMS `CreateKey` and `ListAliases`, Secrets
Manager `GetRandomPassword`, service-linked-role creation with an exact service condition,
ECS/ELB/Application Auto Scaling creation and registration, Cloud Map service creation with
a product request-tag condition, CloudWatch alarm discovery, and the documented WAF/ALB
association read or disassociation calls. Deployment contract tests keep broad IAM, KMS,
S3, Secrets Manager, and ECR administration from returning.

`NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_ACCOUNT_CENTER_URL` are immutable Web build-time
values recorded in the release manifest; neither is mutable ECS runtime configuration.

## Release contract

CI and deployment use four workflows:

1. `CI` runs the repository gates and image build tests.
2. `Publish immutable release` runs automatically only after successful `main` CI. It
   builds linux/amd64 images, emits SBOM/provenance attestations, exports the Web image
   and private source-map index from one BuildKit graph, conditionally writes every map,
   and writes one immutable `releases/<sha>/manifest.json`.
3. `Run protected product migration` clones only the reviewed migration task definition,
   replaces its API image with the selected manifest digest, runs it once, checks the
   container exit code, and deregisters that candidate revision.
4. `Deploy immutable release` verifies the manifest against the checked-out source,
   deploys the runtime stack through its CloudFormation service role, waits for all ECS
   services, and checks Web and API health through Cloudflare.

Publishing never changes production. Deploy and rollback both select an exact 40-character
commit SHA already contained in `main`. Rollback redeploys an older immutable manifest; it
does not move tags, rebuild images, reverse a migration, or restore a database snapshot.

The runtime template exceeds CloudFormation's inline limit. The production workflow uses
the release bucket's short-lived `cloudformation/<sha>/` prefix. Release manifests remain
immutable; CloudFormation packages expire after 30 days and source maps after 365 days.

## One-time AWS setup

The first foundation creation must use an administrator session because the stack creates
the OIDC and CloudFormation roles that protect all later updates:

```bash
delegation_secret_arn=$(aws cloudformation list-exports \
  --region ap-southeast-1 \
  --query 'Exports[?Name==`sanchezcloud-scholight-mcp-delegation-secret-arn`].Value|[0]' \
  --output text)
delegation_kms_key_arn=$(aws cloudformation list-exports \
  --region ap-southeast-1 \
  --query 'Exports[?Name==`sanchezcloud-scholight-configuration-key-arn`].Value|[0]' \
  --output text)
test "$delegation_secret_arn" != None
test "$delegation_kms_key_arn" != None

aws cloudformation validate-template \
  --region ap-southeast-1 \
  --template-body file://deploy/ecs/scholens-foundation.yml

aws cloudformation deploy \
  --region ap-southeast-1 \
  --stack-name sanchezcloud-scholens-foundation \
  --template-file deploy/ecs/scholens-foundation.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --tags \
    System=SanchezCloud \
    Product=Scholens \
    Environment=production \
    ManagedBy=CloudFormation \
  --parameter-overrides \
    GitHubOidcProviderArn=<provider-arn> \
    ProductionDomain=scholens.sanchezcloud.net \
    AlertEmail=<operator-email> \
    ScholightMcpDelegationSecretArn="$delegation_secret_arn" \
    ScholightMcpDelegationKmsKeyArn="$delegation_kms_key_arn"
```

Those exports exist only after the reviewed Scholight delegation-secret change is
deployed. The raw UTF-8 foundation template stays below 48 KiB, so first creation uses
CloudFormation `TemplateBody` directly and never depends on an unmanaged bootstrap bucket.
Standard resource tags are inherited from the four stack tags above; the protected
foundation workflow supplies the same tags on every later update.

Confirm the SNS email subscription. Later foundation changes use the protected
`Update production foundation` workflow; `plan` creates, describes, and deletes a change
set, while `apply` executes a reviewed update through the stack service role.

Request the ACM certificate in `ap-southeast-1`, create its DNS validation CNAME in
Cloudflare, and wait for `ISSUED`. The runtime stack accepts only the certificate ARN; it
does not own DNS.

## Secrets and database roles

CloudFormation creates secret containers, not external provider credentials or PostgreSQL
roles. Never copy production secret values into GitHub.

Required secret groups are:

- `/sanchezcloud/database/scholens-runtime` and `-migrator`;
- `/sanchezcloud/scholens/production/core`;
- `/sanchezcloud/scholens/production/ai-providers`;
- `/sanchezcloud/scholens/production/mail`;
- `/sanchezcloud/scholens/production/billing`;
- `/sanchezcloud/scholens/production/integrations`;
- `/sanchezcloud/scholens/production/edge`.

Generate independent values for every JWT, HMAC, session, cursor, encryption, callback,
and origin token. Provider fields must be filled with the corresponding production
credentials. The shared Scholight delegation secret is imported read-only from Scholight's
foundation and is not copied into a Scholens secret.

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
idempotent and keeps `auth` and `scholens` ownership separate. The runtime role cannot run
DDL; the product migrator cannot modify `auth.*`.

## GitHub environments

Create four protected environments. `production`, `database-production`, and
`infrastructure-production` require a reviewer.

| Environment | Variables |
| --- | --- |
| `image-publish` | `AWS_REGION`, `AWS_PUBLISH_ROLE_ARN`, `IDENTITY_READER_APP_ID`, `PRODUCTION_API_URL`, `ACCOUNT_CENTER_URL` |
| `database-production` | `AWS_REGION`, `AWS_DATABASE_ROLE_ARN` |
| `production` | `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `AWS_CLOUDFORMATION_ROLE_ARN`, `PRODUCTION_DOMAIN`, `PRODUCTION_API_URL`, `ACCOUNT_CENTER_URL`, `PRODUCTION_CERTIFICATE_ARN`, `RDS_SECURITY_GROUP_ID`, `STRIPE_MONTHLY_PRICE_ID`, `STRIPE_YEARLY_PRICE_ID`, `POSTHOG_API_KEY` |
| `infrastructure-production` | `AWS_REGION`, `AWS_INFRASTRUCTURE_ROLE_ARN`, `AWS_CLOUDFORMATION_ROLE_ARN`, `AWS_GITHUB_OIDC_PROVIDER_ARN`, `PRODUCTION_DOMAIN`, `ALERT_EMAIL` |

`IDENTITY_READER_PRIVATE_KEY` is the only repository dependency-reader secret. AWS access
uses OIDC; there are no long-lived AWS access keys in GitHub.

## Cloudflare boundary

Create a proxied CNAME for `scholens.sanchezcloud.net` pointing to the runtime stack's
`LoadBalancerDnsName`. Configure Cloudflare to send `x-scholens-origin` with the
`origin_token` value from the edge secret. Do not expose that value to browser code.

Use Full (strict) TLS, preserve the `Host` header, and keep proxying enabled. The WAF blocks
requests that bypass Cloudflare or omit the origin header, then applies AWS managed common
threat/IP reputation rules and a `CF-Connecting-IP` rate limit. Verify that the ALB DNS name
fails without the header and the public hostname succeeds through Cloudflare.

## First release

1. Merge the reviewed release implementation into `main` and let CI pass.
2. Create the foundation stack, confirm SNS, fill all required secrets, create database
   roles/grants, and validate the ACM certificate.
3. Configure the four GitHub environments and Cloudflare origin rule.
4. Let `Publish immutable release` create the first manifest.
5. Run `Deploy immutable release` for that SHA with `ApplicationEnabled=false` and
   `SchedulerState=DISABLED`. This creates the reviewed migration task while every service
   remains at zero.
6. Run `Run protected product migration` for the same SHA, then rerun
   `database-bootstrap.sql` as the database owner to refresh runtime grants.
7. Deploy the same SHA with `ApplicationEnabled=true`, still with the scheduler disabled.
8. Point the proxied Cloudflare CNAME at the ALB and pass Web, authentication, upload,
   document, research, callback, queue-drain, billing-webhook, Zotero, source-map, alarm,
   and autoscaling checks.
9. Enable the scheduler only after the one-shot job and maintenance queue are verified.

## Capacity and failure handling

- Web scales 2–6 and API scales 2–8 on CPU, memory, and ALB request targets.
- Workers scale on SQS backlog per running task. Scale-in is deliberately slower than
  scale-out, SQS visibility is 45 minutes, and workers request task protection while a job
  is active.
- Queue DLQs, oldest-message age, ALB 5xx, and unhealthy target alarms publish to the
  Scholens SNS topic.
- ECS services use deployment circuit-breaker rollback. A failed database task does not
  change application services. A failed smoke check is still a failed release even if the
  CloudFormation stack stabilized.
- Never delete a retained resource, release manifest, or digest during incident response.

Local verification is side-effect free:

```bash
./scripts/run-gates.sh deployment
```

That lane lints both templates, rejects YAML aliases unsupported by CloudFormation, and
runs the deployment, manifest, and runtime-entrypoint contract tests. AWS API validation
is performed separately with an authenticated operator session.
