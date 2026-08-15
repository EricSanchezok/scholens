# Development Setup

Four application services can run locally: **server** (API), the new **web** foundation,
the legacy **client** used only for comparison, and **jobs** (Celery). Storybook runs
independently for isolated component development. More detail:
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

| Service           | Host port | Start                                          |
| ----------------- | --------- | ---------------------------------------------- |
| Web (canonical)   | 7300      | `pnpm dev` in `web/`                           |
| Server API        | 7301      | `uv run --frozen --no-sync scholens serve` in `server/` |
| Jobs API          | 7302      | `uv run --frozen --no-sync start` in `jobs/`   |
| Legacy client     | 7303      | `corepack yarn dev` in `client/`               |
| Storybook         | 7306      | `pnpm storybook` in `web/`                     |
| Flower (optional) | 7307      | `./scripts/start_flower.sh`                    |

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

| Runtime file        | Owned configuration                                     |
| ------------------- | ------------------------------------------------------- |
| `server/.env`       | Database, sanchezcloud-identity, MOSS, API integrations |
| `jobs/.env`         | MinerU, background processing, webhook delivery         |
| Both Python files   | S3, AI profiles, broker URLs, webhook signing secret    |
| `web/.env.local`    | canonical `NEXT_PUBLIC_*` browser configuration         |
| `client/.env.local` | legacy comparison client configuration                  |

Do not copy Python-service credentials into `client/.env.local`. Next.js only
exposes `NEXT_PUBLIC_*` values to browser code, but keeping secrets out of the
client build context is the safer operational boundary.

**Must match across server and jobs:** `CELERY_BROKER_URL`, S3/AWS bucket vars,
`SCHOLENS_AI_*`, and `JOBS_WEBHOOK_SIGNING_SECRET`. Server needs
`CELERY_API_URL=http://127.0.0.1:7302`; jobs needs
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
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`                                                      | server + jobs                                                   |
| `CELERY_API_URL`                                                                                  | server                                                          |
| `WEBHOOK_BASE_URL`                                                                                | jobs                                                            |
| `AUTH_JWT_SECRET` (32+ bytes)                                                                     | server                                                          |
| `AUTH_ALIYUN_DM_ACCESS_KEY_ID`, `AUTH_ALIYUN_DM_ACCESS_KEY_SECRET`, `AUTH_ALIYUN_DM_ACCOUNT_NAME` | server; verification/reset mail                                 |
| `CLIENT_DOMAIN`                                                                                   | server canonical URL (`http://127.0.0.1:7300`)                  |
| `CLIENT_ALLOWED_ORIGINS`                                                                          | server (`http://127.0.0.1:7300,http://127.0.0.1:7303`)          |
| `NEXT_PUBLIC_API_URL`                                                                             | web + legacy client                                             |
| `NEXT_PUBLIC_ACCOUNT_CENTER_URL`                                                                  | web; optional Account Center override (`http://127.0.0.1:7100`) |

MOSS Voice is required only for audio overviews. Zotero, Stripe, email, PostHog,
and admin variables are grouped in the root `.env.example`.

Settings → Account defaults to the canonical
`https://myaccount.sanchezcloud.net` destination. Set
`NEXT_PUBLIC_ACCOUNT_CENTER_URL` only when the environment intentionally uses a
different Account Center host, such as local Account Center on port `7100`.

Scholens discovers remote model tools through MCP. Scholight is the built-in
provider: `SCHOLIGHT_MCP_URL` selects its fixed endpoint and
`SCHOLIGHT_MCP_DELEGATION_JWT_SECRET` signs a fresh 60-second delegation for the
current user. AnySearch, Tavily, Exa, and Firecrawl are connected per user in
Settings; MinerU is connected there as well. All user-owned credentials are
encrypted with `INTEGRATION_CREDENTIAL_ENCRYPTION_KEY` and are released to a
worker only for a claimed, owner-scoped job.

For an opt-in local-to-local integration check, start Scholight on its documented
loopback API port, set the ignored Scholens `server/.env` value to
`SCHOLIGHT_MCP_URL=http://127.0.0.1:7201/mcp`, and configure the same delegation
secret in both services. Keep each product on its own schema in the shared local
PostgreSQL database. A complete smoke test must confirm that the Conversation
agent sees both Scholens `search_saved_papers` and Scholight `search_papers`, can
invoke the latter through Scholight, and reports no `connector_tool_name_conflict`.
Do not commit local secrets or replace the production runtime endpoint while
performing this check.

**Jobs tip:** set `ZOTERO_SYNC_INTERVAL_SECONDS=60` in `jobs/.env` when testing Celery Beat locally.

### Local and remote dependency policy

`sanchezcloud-identity` is embedded in the Scholens API; it is not a separate service.
Unless `AUTH_DATABASE_URL` is explicitly set, both sanchezcloud-identity and Scholens use
`DATABASE_URL`.

- Local development always uses the shared `sanchezcloud` database at
  `127.0.0.1:55432`. The Server start command rejects every other database endpoint,
  including RDS and the ordinary local port `5432`.
- RDS settings belong only in deployment-managed production environments; see
  [`deploy/production/runtime.env.example`](./deploy/production/runtime.env.example).
- Scholens and Scholight deliberately use different JWT secrets and
  `client_id` values even though they share `auth.users`.
- Products may use the same Aliyun DirectMail account, while keeping sender
  aliases and action URLs product-specific. Scholens local authentication sends
  real mail through Aliyun; there is no Mailpit profile.
- Scholens local development uses a dedicated remote dev S3 bucket with
  least-privilege development credentials. Leave `AWS_ENDPOINT_URL_S3` empty
  for AWS S3 and never point local credentials at a production bucket.
- Remote model/search providers (DeepSeek, MinerU, MOSS Voice, Scholight MCP,
  and user-configured MCP connectors) are opt-in. Use them only when the feature
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

Create roles and schemas with a local database administrator following the
[sanchezcloud-identity handbook](https://github.com/EricSanchezok/sanchezcloud-identity/blob/main/docs/guides/local-development.md).
`scholens_migrator` owns and migrates the product schema; `scholens_app` is the
runtime role and must not own schemas. Alembic intentionally refuses to migrate
a `scholens` schema owned by another role. Never use the server's daily runtime
command as a migration shortcut.

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

The default profile is Server + Web. Add Jobs only for uploads, parsing,
background processing, or Zotero synchronization. The legacy client,
Storybook, and Flower are opt-in profiles.

Use separate terminals:

| Profile | Directory       | Command                                                                      |
| ------- | --------------- | ---------------------------------------------------------------------------- |
| Infra   | repository root | `docker compose -f jobs/compose.local.yaml up -d redis` — AI limits on 56379 |
| Default | `server/`       | `uv run --frozen --no-sync scholens serve` — validate local PostgreSQL; API 7301 |
| Default | `web/`          | `pnpm dev` — canonical web on 7300                                           |
| Jobs    | `jobs/`         | `uv run --frozen --no-sync start` — broker, worker, Beat, and API 7302       |
| Legacy  | `client/`       | `corepack yarn dev` — comparison UI on 7303                                  |
| UI      | `web/`          | `pnpm storybook` — isolated components on 7306, no Server required           |
| Observe | `jobs/`         | `./scripts/start_flower.sh` — Flower on 7307 after RabbitMQ is available     |

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

Redis is required whenever `AI_LIMIT_REDIS_URL` is configured, including Home
conversation testing. The local value is
`redis://127.0.0.1:56379/1`; port 6379 is the container-only port. The Compose
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
local-only reset requires an exact `--actor-email`, a non-empty `--reason`, and
interactive confirmation or `--yes`. The actor must be an active, verified,
unblocked Scholens administrator. Repeated idempotent operations report
`unchanged`; failures use exit code 1 and Click parameter errors use exit code
2. Entitlement and quota reasons are persisted on their product records.
Identity admin/block reasons are required operator rationale but are not
persisted; their append-only Journal entries retain only the safe command,
actor, action, and resource projection. The CLI never exposes a general
job-state editor, Token Credit reset,
Stripe-subscription editor, or remote database-reset command.

`maintenance backfill-passages --batch-size N --apply` processes at most `N`
documents in one invocation and one application transaction. Re-run it until
the reported candidate count reaches zero. It uses ordinary row DML and the
existing search-vector trigger; the runtime role never receives trigger or
table DDL privileges.

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

## Pre-release schema policy

Scholens is currently pre-release. A breaking product schema or public API
change must leave one canonical contract, not a compatibility period. Remove
the superseded column, route, DTO, workflow, fixture, and test together. Do not
add dual reads, dual writes, legacy adapters, feature flags, or data backfills
solely to keep disposable local product rows alive.

For breaking data-model work, reset the local `scholens` schema and rebuild the
target schema. Alembic remains the reproducible schema builder; an unreleased
revision is not a promise to migrate user data forever. Prefer replacing or
squashing unreleased revisions over stacking transformations whose only value
is preserving pre-release data. This policy changes only through an explicit
release-readiness decision that also defines production migration and rollback
requirements.

## Reset only the local product schema

Scholens owns `scholens`; sanchezcloud-identity independently owns `auth`.
Local product data is disposable during this pre-release phase, but `auth`
must never be dropped. Configure `LOCAL_DATABASE_ADMIN_URL` and
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
