# Development Setup

Four application services can run locally: **server** (API plus its dedicated
Conversation worker), the new **web** foundation, the legacy **client** used only
for comparison, and **jobs** (Celery). Storybook runs independently for isolated
component development. More detail:
[server/README.md](./server/README.md), [web/README.md](./web/README.md),
[client/README.md](./client/README.md), [jobs/README.md](./jobs/README.md).

## Prerequisites

Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 22 LTS, Corepack,
PostgreSQL, and Docker (RabbitMQ + Redis for jobs). The deployment gate also
requires `shellcheck` and `cfn-lint`; install the latter with
`uv tool install cfn-lint`. Avoid odd-numbered Node releases; the frontend
dependency graph follows the active/LTS Node support window enforced in
`client/package.json`.

## Local development contract

Scholens owns the `7300-7399` host-port block. Local services bind only to
`127.0.0.1`, use the fixed ports below, and fail when a port is occupied. Do not
add automatic port fallback or borrow a port from Account Center (`7100-7199`)
or Scholight (`7200-7299`). Container-internal production ports are not part of
this host-port contract.

| Service           | Host port | Start                                                   |
| ----------------- | --------- | ------------------------------------------------------- |
| Web (canonical)   | 7300      | `pnpm dev` in `web/`                                    |
| Server API        | 7301      | `uv run --frozen --no-sync scholens serve` in `server/` |
| Conversation worker | none    | `uv run --frozen --no-sync celery --app app.modules.conversations.infrastructure.celery_app worker --loglevel=info --concurrency=1 --queues=conversation --without-gossip --without-mingle` in `server/` |
| Jobs API          | 7302      | `uv run --frozen --no-sync start` in `jobs/`            |
| Legacy client     | 7303      | `corepack yarn dev` in `client/`                        |
| Storybook         | 7306      | `pnpm storybook` in `web/`                              |
| Flower (optional) | 7307      | `./scripts/start_flower.sh`                             |

Shared local infrastructure uses ports outside all product blocks:

| Infrastructure | Host endpoint             | Container port |
| -------------- | ------------------------- | -------------- |
| PostgreSQL     | `127.0.0.1:55432`         | 5432           |
| RabbitMQ       | `amqp://127.0.0.1:55672`  | 5672           |
| Redis          | `redis://127.0.0.1:56379` | 6379           |

Ports `59000/59001` are reserved for projects that explicitly choose local
MinIO. Scholens does not start or consume MinIO in its default local workflow;
it uses an isolated remote dev S3 bucket instead. This project-specific choice
does not require Scholight or Account Center to use the same provider.

The PostgreSQL database is shared with Account Center and Scholight, but schema
ownership is not: sanchezcloud-identity migrates only `auth.*`; Scholens migrates
only `scholens.*`. Local product startup must never connect to RDS, and no daily
startup command may install dependencies or apply migrations.

## Environment files

Scholens follows the same “one documented environment catalog” convention as
Scholight. The canonical template is [`.env.example`](./.env.example). Create
each runtime file from the relevant section of that catalog:

S3、MinerU、MOSS Voice 和 DeepSeek 的账号申请步骤见
[`docs/setup/external-services.zh-CN.md`](./docs/setup/external-services.zh-CN.md)。

```bash
touch server/.env jobs/.env web/.env.local client/.env.local
```

The root file is a committed catalog, not a runtime file. Each process reads
the private file in its own working directory:

| Runtime file        | Owned configuration                                        |
| ------------------- | ---------------------------------------------------------- |
| `server/.env`       | Database, sanchezcloud-identity, MOSS, API integrations    |
| `jobs/.env`         | MinerU, background processing, webhook delivery            |
| Both Python files   | S3, AI profiles, broker/cache URLs, webhook signing secret |
| `web/.env.local`    | canonical `NEXT_PUBLIC_*` browser configuration            |
| `client/.env.local` | legacy comparison client configuration                     |

Do not copy Python-service credentials into `client/.env.local`. Next.js only
exposes `NEXT_PUBLIC_*` values to browser code, but keeping secrets out of the
client build context is the safer operational boundary.

**Must match across server and jobs:** `CELERY_BROKER_URL`, `CACHE_URL`, S3/AWS
bucket vars, `SCHOLENS_AI_*`, and `JOBS_WEBHOOK_SIGNING_SECRET`. Jobs needs
`WEBHOOK_BASE_URL=http://127.0.0.1:7301`.

AI configuration has one canonical namespace: `SCHOLENS_AI_*`. Remove obsolete
unprefixed `DEEPSEEK_*` variables after moving their current credential and
endpoint values; the runtime intentionally provides no alias or fallback for
the superseded names.

### Required for a minimal local stack

| Variable                                                                                          | Where                                                           |
| ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `DATABASE_URL`                                                                                    | server                                                          |
| `SCHOLENS_AI_DEEPSEEK_API_KEY`                                                                    | server, jobs (for the current default profiles)                 |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `CLOUDFLARE_BUCKET_NAME`          | server + jobs; isolated remote dev S3                           |
| `CELERY_BROKER_URL`, `CACHE_URL`                                                                  | server + jobs                                                   |
| `WEBHOOK_BASE_URL`                                                                                | jobs                                                            |
| `AUTH_JWT_SECRET` (32+ bytes)                                                                     | server                                                          |
| `SCHOLENS_ALIYUN_DM_ACCESS_KEY_ID`, `SCHOLENS_ALIYUN_DM_ACCESS_KEY_SECRET`, `SCHOLENS_ALIYUN_DM_ACCOUNT_NAME` | server; identity and Project invitation mail                    |
| `CLIENT_DOMAIN`                                                                                   | server canonical URL (`http://127.0.0.1:7300`)                  |
| `CLIENT_ALLOWED_ORIGINS`                                                                          | server (`http://127.0.0.1:7300,http://127.0.0.1:7303`)          |
| `NEXT_PUBLIC_API_URL`                                                                             | web + legacy client                                             |
| `NEXT_PUBLIC_ACCOUNT_CENTER_URL`                                                                  | web; optional Account Center override (`http://127.0.0.1:7100`) |
| `NEXT_PUBLIC_RELEASE_SHA`                                                                         | web build metadata; `development` uses labeled mutable fallback |

MOSS Voice is required only for audio overviews. Zotero and admin variables are
grouped in the root `.env.example`. Public charging and PostHog are intentionally
disabled in the current production release and have no ordinary runtime
configuration.

Settings → Account defaults to the canonical
`https://myaccount.sanchezcloud.net` destination. Set
`NEXT_PUBLIC_ACCOUNT_CENTER_URL` only when the environment intentionally uses a
different Account Center host, such as local Account Center on port `7100`.

Scholens discovers remote model tools through MCP. Scholight is the built-in
provider: `SCHOLIGHT_MCP_URL` selects its fixed endpoint and
`SCHOLIGHT_MCP_DELEGATION_JWT_SECRET` signs a fresh 60-second delegation for the
current user. AnySearch, Tavily, Exa, and Firecrawl are connected per user in
Settings; MinerU and OpenAlex are connected there as well. OpenAlex uses the
official fixed REST endpoint rather than MCP, and its key is never a local or
production environment variable. All user-owned credentials are encrypted with
`INTEGRATION_CREDENTIAL_ENCRYPTION_KEY`; job credentials are released only for
a claimed, owner-scoped job, while OpenAlex is resolved for the current actor's
Server request.

For an opt-in local-to-local integration check, start Scholight on its documented
loopback API port, set the ignored Scholens `server/.env` value to
`SCHOLIGHT_MCP_URL=http://127.0.0.1:7201/mcp`, and configure the same delegation
secret in both services. Keep each product on its own schema in the shared local
PostgreSQL database. A complete smoke test must confirm that the Conversation
agent sees both Scholens `search_scholens_knowledge` and Scholight `search_papers`, can
invoke the latter through Scholight, and reports no `connector_tool_name_conflict`.
Do not commit local secrets or replace the production runtime endpoint while
performing this check.

Inbound MCP is a separate direction: external Agents authenticate to the
Server's `/mcp` endpoint with a Scholens Access Key. To test local PDF paths,
provision the official bridge explicitly and run its isolated gate:

```bash
uv sync --directory mcp-connector
./scripts/run-gates.sh mcp-connector
```

Configure the host as documented in
[`mcp-connector/README.md`](./mcp-connector/README.md). Prefer
`SCHOLENS_ACCESS_KEY` in the host's secret environment and expose only the
research repository as an MCP root (or `--allowed-root`). The bridge is stdio,
opens no inbound port, and works on a computer without a public IP.

**Jobs tip:** set `ZOTERO_SYNC_INTERVAL_SECONDS=60` in `jobs/.env` when testing Celery Beat locally.

### Local and remote dependency policy

`sanchezcloud-identity` is embedded in the Scholens API; it is not a separate service.
Unless `AUTH_DATABASE_URL` is explicitly set, both sanchezcloud-identity and Scholens use
`DATABASE_URL`.

- Local development always uses the shared `sanchezcloud` database at
  `127.0.0.1:55432`. The Server start command rejects every other database endpoint,
  including RDS and the ordinary local port `5432`.
- RDS split fields belong only in the ECS production environment; see
  [`deploy/ecs/README.md`](./deploy/ecs/README.md).
- Scholens and Scholight deliberately use different JWT secrets and
  `client_id` values even though they share `auth.users`.
- Products may use the same Aliyun DirectMail account, while keeping sender
  aliases and action URLs product-specific. Scholens authentication and durable
  Project invitations send real mail through Aliyun; there is no Mailpit profile.
  Both use `CLIENT_DOMAIN` for Scholens links and the `SCHOLENS_ALIYUN_DM_*`
  settings; no identity-prefixed mail configuration exists.
- Scholens local development uses a dedicated remote dev S3 bucket with
  least-privilege development credentials. Leave `AWS_ENDPOINT_URL_S3` empty
  for AWS S3 and never point local credentials at a production bucket.
- Remote model/search providers (DeepSeek, MinerU, MOSS Voice, Scholight MCP,
  OpenAlex, and user-configured MCP connectors) are opt-in. Use them only when the feature
  under test requires them and never commit their credentials.

## First-time setup

```bash
git clone <your-scholens-fork-url> scholens && cd scholens

# Install the exact locked dependencies (first time or after lockfile changes)
cd server && uv sync --frozen --group dev
cd ../jobs && uv sync --frozen --group dev
cd ../packages && uv sync --frozen --all-packages --group dev
cd ../client && corepack yarn install --frozen-lockfile
cd ../web && corepack pnpm install --frozen-lockfile

# Install the deployment-contract linter outside the project environments.
uv tool install cfn-lint

# Create private runtime files by copying only each service's section from
# .env.example; do not copy the complete catalog into browser runtimes.
cd ..
touch server/.env jobs/.env web/.env.local client/.env.local

# Provision identity from sanchezcloud-identity first. Then provision the local
# product owner/role and apply Scholens migrations explicitly with the migrator.
cd server
SCHOLENS_MIGRATION_DATABASE_URL='postgresql+psycopg2://scholens_migrator:<local-password>@127.0.0.1:55432/sanchezcloud' \
  uv run scholens db upgrade --yes
SCHOLENS_MIGRATION_DATABASE_URL='postgresql+psycopg2://scholens_migrator:<local-password>@127.0.0.1:55432/sanchezcloud' \
  uv run scholens db status
```

Shared profile avatars are optional locally. Leave `SHARED_AVATAR_BUCKET`
empty for deterministic initial fallbacks. To exercise real images, configure
only the isolated non-production avatar bucket and AWS credentials explicitly;
never point local Scholens at the production shared-avatar bucket. Scholens does
not start MinIO for avatars.

Create roles and schemas with a local database administrator following the
[sanchezcloud-identity handbook](https://github.com/EricSanchezok/sanchezcloud-identity/blob/main/docs/guides/local-development.md).
Before applying Scholens migrations, that administrator must install
`pg_trgm` and `vector` in the shared database's `public` schema. The database
image therefore needs pgvector support; the product migrator deliberately
cannot install extensions.
`scholens_migrator` owns and migrates the product schema; `scholens_app` is the
runtime role and must not own schemas. Alembic intentionally refuses to migrate
a `scholens` schema owned by another role. Never use the server's daily runtime
command as a migration shortcut.

### Seed a reusable local test account

Use the guarded fixture command instead of repeatedly registering through real
mail or adding an authentication bypass:

```bash
cd server
uv run --frozen --no-sync scholens dev seed-test-account
```

The hidden prompt requires a password of at least 12 characters. The default
identity is `developer@example.com` with display name `Local Developer`.
Alternatively, keep `SCHOLENS_DEV_TEST_PASSWORD` only in ignored `server/.env`
for repeatable local automation. The command accepts only reserved synthetic
email domains and refuses every environment except `development` connected as
`scholens_app` to `127.0.0.1:55432/sanchezcloud`.

The command is idempotent: it creates and verifies a missing Identity account,
creates its Scholens profile, and leaves matching credentials and sessions
unchanged. Supplying a different password uses the Identity password-reset path
and therefore revokes the account's existing sessions. `--bootstrap-admin` is
optional and works only when Scholens has no administrator yet. Daily startup
never creates or changes accounts.

### Repair a prepared checkout

If a checkout moves, a Python virtual environment still references an old
absolute path, or a dependency directory becomes incomplete, stop the local
services and rerun the locked sync commands above in the affected directory.
Never copy or borrow `.venv`, `node_modules`, or generated build output from
another checkout. Confirm the active frontend runtime with `node --version`;
it must report Node 22 before installing dependencies or running gates.

If a Python launcher still has a shebang for the old checkout after a normal
sync, rebuild that service's installed environment from the same lockfile with
`uv sync --frozen --group dev --reinstall`. Use the equivalent
`--all-packages --group dev --reinstall` form for `packages/`. Verify that no
script under the affected `.venv/bin` contains the previous checkout path.

This is an explicit maintenance operation, not part of daily startup. The
`--frozen`/`--frozen-lockfile` flags repair installed environments without
changing committed dependency resolution. If a lockfile itself must change,
make that a reviewed dependency update and commit the manifest and lockfile
together.

## Start locally (daily)

The default profile is Server API + Conversation worker + Web. Add Jobs only for uploads, parsing,
background processing, or Zotero synchronization. The legacy client,
Storybook, and Flower are opt-in profiles.

Use separate terminals:

| Profile | Directory       | Command                                                                          |
| ------- | --------------- | -------------------------------------------------------------------------------- |
| Infra   | repository root | `docker compose -f jobs/compose.local.yaml up -d rabbitmq redis` — durable Conversation delivery and AI limits |
| Default | `server/`       | `uv run --frozen --no-sync scholens serve` — validate local PostgreSQL; API 7301 |
| Default | `server/`       | `uv run --frozen --no-sync celery --app app.modules.conversations.infrastructure.celery_app worker --loglevel=info --concurrency=1 --queues=conversation --without-gossip --without-mingle` |
| Default | `web/`          | `pnpm dev` — canonical web on 7300                                               |
| Jobs    | `jobs/`         | `uv run --frozen --no-sync start` — broker, worker, Beat, and API 7302           |
| Legacy  | `client/`       | `corepack yarn dev` — comparison UI on 7303                                      |
| UI      | `web/`          | `pnpm storybook` — isolated components on 7306, no Server required               |
| Observe | `jobs/`         | `./scripts/start_flower.sh` — Flower on 7307 after RabbitMQ is available         |

The Web development server writes its disposable Next.js output to
`web/.next-dev/`; production verification writes to `web/.next/`. Keeping the
two directories separate prevents `pnpm build` from replacing CSS and route
artifacts underneath an active local development server.

Check: [127.0.0.1:7301/docs](http://127.0.0.1:7301/docs),
[127.0.0.1:7300](http://127.0.0.1:7300), and, when enabled,
[127.0.0.1:7302](http://127.0.0.1:7302),
[127.0.0.1:7303](http://127.0.0.1:7303), and
[127.0.0.1:7306](http://127.0.0.1:7306). Confirm the worker log shows
`celery@... ready` when using the Jobs profile.

Redis is required whenever `CACHE_URL` is configured, including Home
conversation testing and resumable PDF processing. The local value is
`redis://127.0.0.1:56379/0`; port 6379 is the container-only port. The Compose
services use `restart: unless-stopped`, so they return with Docker after a host
restart unless they were explicitly stopped.

If any registered port is occupied, stop the conflicting process or change the
other project's contract deliberately in all affected repositories. Do not
silently select a random port, because callback URLs, CORS, cookies, tests, and
service-to-service URLs rely on these stable endpoints.

## Operator and development CLI

Run `uv run scholens --help` from `server/`. The unified entry point owns local
serving, dependency diagnostics, user/admin inspection, product entitlement
grants, temporary quota overrides, usage reports, safe job inspection,
migrations, contract generation, deterministic verification, and guarded
maintenance/development operations. Put `--json` after any concrete command
for automation, for example `uv run scholens users show --email ... --json`.

Every business write other than first-admin bootstrap and the destructive
local-only reset requires an exact `--actor-email` and interactive confirmation
or `--yes`. Entitlement and quota commands also require `--reason`, which
persists on their product records. Identity, development, and maintenance
commands do not collect arbitrary reason prose;
their append-only Journal entries retain the structured command, actor, action,
and resource projection. The actor must be active, verified, and unblocked.
Repeated idempotent operations report `unchanged`; failures use exit code 1 and
Click parameter errors use exit code 2. The CLI never exposes a general job-state
editor, Token Credit reset,
Stripe-subscription editor, or remote database-reset command.

Operator authorization is transaction-scoped: privileged commands lock the
administrator roster and then re-read the actor's locked identity/profile
projection. Revoke and block use the same lock order, preventing a previously
read admin snapshot from authorizing a later write after privilege reduction.

`maintenance backfill-passages --batch-size N --apply` processes at most `N`
documents in one invocation and one application transaction. Re-run it until
the reported candidate count reaches zero. It uses ordinary row DML and the
existing search-vector trigger; the runtime role never receives trigger or
table DDL privileges.

Two evidence-bound repair commands are dry-run by default and require `--apply`
to mutate data: `maintenance fix-annotation-offsets` reanchors only a unique
verbatim quote, leaving missing or repeated quotes unresolved, and
`maintenance reprocess-contaminated-documents` queues only the current completed
PDF job when its persisted result object key differs from its canonical
Document. Both accept `--batch-size N`; rerun the dry-run after each applied
batch and inspect unresolved samples before taking any manual action.

Useful read-only diagnostics include:

```bash
uv run scholens doctor --json
uv run scholens users list --plan researcher
uv run scholens usage report --week-start 2026-08-10 --json
uv run scholens jobs failures --json
```

Before adding replacement-frontend product code, read the
[`web/docs` engineering handbook](./web/docs/README.md). It defines dependency
direction, feature slices, component intake, Figma/token synchronization, API
generation, testing responsibilities, and the required new-feature checklist.
The mandatory
[`frontend change governance`](./web/docs/frontend-governance.md) also defines
how to add, modify, and delete pages, modules, components, tokens, themes, and
their Figma/Storybook acceptance evidence. Run `pnpm design:check` after any
styling, token, theme, adapter, component-state, or Storybook-global change.

## Quality gates

The repository exposes one canonical, side-effect-free gate interface:

```bash
./scripts/run-gates.sh <server|jobs|shared-packages|web|client|deployment|docs|all>
```

Run it from the repository root after explicitly preparing the locked
environments in the setup section above. The runner validates only: it does not
install or update dependencies, start persistent local services, apply
migrations, or modify product data. Browser-test runners may create and clean
up an ephemeral web server for their lane. Use the narrowest affected lane
during development and `all` for repository-wide governance or before a
cross-repository `main` merge. CI provisions its own environments and then
calls these same lanes, so the executable contract cannot drift from the
documented commands.

Detailed leaf checks and test ownership remain in the owning service guides.
The `docs` lane validates repository documentation and ADR structure; it is
also included in the Web lane because Web owns the documentation checker.

## Production schema policy

Production data and every applied migration are durable. Never edit, rename,
delete, reorder, or squash an existing file under
`server/migrations/versions`; add a new revision and classify it in
`server/migrations/policy.json`. Changes use separate
expand–migrate–switch–contract releases. Large or interruptible data movement
belongs in a bounded, restartable operator command rather than an Alembic
transaction.

Production application rollback does not run Alembic downgrade. The release
contract records a monotonic minimum compatible application revision and may
select an older image only within that live range. Full authoring, temporary
adapter, backfill, deprecation, and contract-removal requirements are in
[`docs/architecture/contract-evolution.md`](./docs/architecture/contract-evolution.md).

## Reset only the local product schema

Scholens owns `scholens`; sanchezcloud-identity independently owns `auth`.
The guarded reset remains available only for an intentionally disposable local
product environment; it is not a migration rehearsal or production recovery
method. `auth` must never be dropped. Configure `LOCAL_DATABASE_ADMIN_URL` and
`SCHOLENS_MIGRATION_DATABASE_URL` for exactly
`127.0.0.1:55432/sanchezcloud`, then run:

```bash
cd server
uv run scholens dev reset-product
```

The command requires the exact phrase `RESET-SCHOLENS-LOCAL`, drops and
recreates only `scholens`, applies product migrations, reapplies the reviewed
runtime grants, and compares the Identity schema and user count before and
after. It rejects every other host, port, database, or migration role. Use
`uv run scholens db status` afterward for a read-only revision check.

Do not grant ownership to `scholens_app` or grant it either migration ledger.
The bootstrap intentionally leaves the operation journal append-only and is
safe to re-run after both Identity and product migrations.

The migration role must own `scholens` and have read/write access required by
product foreign keys, but it must not own or have `CREATE` on `auth`.
