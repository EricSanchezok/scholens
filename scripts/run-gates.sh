#!/usr/bin/env bash

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPOSITORY_ROOT

usage() {
  cat <<'EOF'
Usage: ./scripts/run-gates.sh <lane>

Available lanes:
  server
  jobs
  shared-packages
  web
  client
  deployment
  docs
  all

The runner only verifies an already-provisioned workspace. It never installs
dependencies, starts persistent development services, or applies database
migrations. Browser-test runners may create and clean up an ephemeral web
server for the duration of their lane.
EOF
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command is not available: %s\n' "$command_name" >&2
    printf 'Provision dependencies explicitly before running this gate.\n' >&2
    exit 1
  fi
}

require_executable() {
  local executable_path="$1"
  if [[ ! -x $executable_path ]]; then
    printf 'Required workspace executable is not available: %s\n' \
      "$executable_path" >&2
    printf 'Provision the locked workspace explicitly before running this gate.\n' >&2
    exit 1
  fi
}

run_server() {
  local environment="$REPOSITORY_ROOT/server/.venv/bin"
  require_executable "$environment/ruff"
  require_executable "$environment/mypy"
  require_executable "$environment/pytest"
  (
    cd "$REPOSITORY_ROOT/server"
    "$environment/ruff" format --check app tests migrations
    "$environment/ruff" check app tests migrations
    "$environment/mypy" app

    if grep -R --exclude-dir=__pycache__ --line-number \
      -E '(^|[^[:alnum:]_])print\(|datetime\.utcnow\(|app\.api\.types' app; then
      printf 'Forbidden legacy or debug pattern found in Server business code\n' >&2
      exit 1
    fi

    "$environment/pytest" -q
  )
}

run_jobs() {
  local environment="$REPOSITORY_ROOT/jobs/.venv/bin"
  require_executable "$environment/ruff"
  require_executable "$environment/mypy"
  require_executable "$environment/pytest"
  (
    cd "$REPOSITORY_ROOT/jobs"
    "$environment/ruff" format --check src tests
    "$environment/ruff" check src tests
    "$environment/mypy" src
    "$environment/pytest" -q
  )
}

run_shared_packages() {
  local environment="$REPOSITORY_ROOT/packages/.venv/bin"
  require_command uv
  require_executable "$environment/python"
  require_executable "$environment/ruff"
  require_executable "$environment/mypy"
  require_executable "$environment/pytest"

  "$environment/python" "$REPOSITORY_ROOT/scripts/check_workspace.py"
  uv lock --check --directory "$REPOSITORY_ROOT/packages"
  uv lock --check --directory "$REPOSITORY_ROOT/server"
  uv lock --check --directory "$REPOSITORY_ROOT/jobs"
  (
    cd "$REPOSITORY_ROOT/packages"
    "$environment/ruff" format --check \
      scholens_ai/src scholens_ai/tests \
      scholens_observability/src scholens_observability/tests
    "$environment/ruff" check \
      scholens_ai/src scholens_ai/tests \
      scholens_observability/src scholens_observability/tests
    "$environment/mypy" scholens_ai/src scholens_observability/src
    "$environment/pytest" -q
  )
}

run_web() {
  require_command pnpm
  (
    cd "$REPOSITORY_ROOT/web"
    pnpm tokens:check
    pnpm api:check
    pnpm i18n:check
    pnpm architecture:check
    pnpm design:check
    pnpm docs:check
    pnpm lint
    pnpm format:check
    pnpm typecheck
    pnpm test
    pnpm test:storybook
    pnpm build-storybook
    NEXT_TELEMETRY_DISABLED=1 pnpm build
    pnpm test:e2e
  )
}

run_client() {
  require_command yarn
  (
    cd "$REPOSITORY_ROOT/client"
    yarn lint
    yarn tsc --noEmit
    yarn test:e2e

    local build_log
    build_log="$(mktemp "${TMPDIR:-/tmp}/scholens-client-build.XXXXXX")"
    trap 'rm -f "$build_log"' EXIT

    set -o pipefail
    NEXT_TELEMETRY_DISABLED=1 yarn build 2>&1 | tee "$build_log"
    if grep -Eiq \
      'window is not defined|document is not defined|please use (the )?legacy build' \
      "$build_log"; then
      printf 'Browser-only PDF.js code leaked into the server build\n' >&2
      exit 1
    fi
  )
}

run_deployment() {
  require_command shellcheck
  require_command cfn-lint
  require_command docker

  (
    cd "$REPOSITORY_ROOT"
    readonly deployment_scripts=(
      deploy/production/release.sh
      deploy/production/smoke.sh
      deploy/production/wait-ssm.sh
      deploy/production/install-observability.sh
      deploy/production/upload-source-maps.sh
    )

    bash -n "${deployment_scripts[@]}"
    shellcheck "${deployment_scripts[@]}"
    cfn-lint deploy/production/observability.yaml

    export SCHOLENS_API_IMAGE=registry.example/scholens/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    export SCHOLENS_CLIENT_IMAGE=registry.example/scholens/client@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    export SCHOLENS_JOBS_IMAGE=registry.example/scholens/jobs@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
    export SCHOLENS_RELEASE_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    export SCHOLENS_DOMAIN=scholens.example.invalid
    export SCHOLENS_AWS_REGION=us-east-1
    export SCHOLENS_APP_DATABASE_URL=postgresql://app:password@postgres.example.invalid/sanchezcloud
    export SCHOLENS_MIGRATION_DATABASE_URL=postgresql://migrator:password@postgres.example.invalid/sanchezcloud
    export SCHOLENS_AUTH_JWT_SECRET=fixture-secret-at-least-thirty-two-bytes
    export SCHOLENS_ADMIN_SESSION_SECRET=fixture-admin-session-secret-at-least-thirty-two-bytes
    export SCHOLENS_PAPER_SEARCH_CURSOR_SECRET=fixture-search-cursor-secret-at-least-thirty-two-bytes
    export SCHOLENS_RABBITMQ_PASSWORD=fixture-rabbit-password
    export SCHOLENS_REDIS_PASSWORD=fixture-redis-password
    export SCHOLENS_ALIYUN_DM_ACCESS_KEY_ID=fixture
    export SCHOLENS_ALIYUN_DM_ACCESS_KEY_SECRET=fixture
    export SCHOLENS_ALIYUN_DM_ACCOUNT_NAME=sender@example.invalid
    export SCHOLENS_S3_BUCKET_NAME=fixture-bucket
    export SCHOLENS_CLOUDFLARE_BUCKET_NAME=fixture-bucket.s3.us-east-1.amazonaws.com
    export SCHOLENS_AI_DEEPSEEK_API_KEY=fixture
    export SCHOLENS_MINERU_API_TOKEN=fixture
    export SCHOLENS_MOSS_API_KEY=fixture
    export SCHOLENS_MOSS_VOICE_ID=fixture
    export SCHOLENS_JOBS_WEBHOOK_SIGNING_SECRET=fixture-signing-secret-at-least-thirty-two-bytes
    export SCHOLENS_SCHOLIGHT_MCP_DELEGATION_JWT_SECRET=fixture-delegation-secret-at-least-thirty-two-bytes
    export SCHOLENS_CONNECTOR_CREDENTIAL_ENCRYPTION_KEY=Zml4dHVyZS1jb25uZWN0b3Ita2V5LTMyLWJ5dGVzISE=
    export SCHOLENS_STRIPE_API_KEY=fixture
    export SCHOLENS_STRIPE_WEBHOOK_SECRET=fixture
    export SCHOLENS_STRIPE_MONTHLY_PRICE_ID=fixture
    export SCHOLENS_STRIPE_YEARLY_PRICE_ID=fixture
    export SCHOLENS_ZOTERO_CLIENT_KEY=fixture
    export SCHOLENS_ZOTERO_CLIENT_SECRET=fixture

    docker compose -f deploy/production/compose.yaml config --quiet
  )
}

run_docs() {
  require_command pnpm
  (
    cd "$REPOSITORY_ROOT/web"
    pnpm docs:check
  )
}

run_all() {
  run_server
  run_jobs
  run_shared_packages
  run_web
  run_client
  run_deployment
  run_docs
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

case "$1" in
  server) run_server ;;
  jobs) run_jobs ;;
  shared-packages) run_shared_packages ;;
  web) run_web ;;
  client) run_client ;;
  deployment) run_deployment ;;
  docs) run_docs ;;
  all) run_all ;;
  -h | --help) usage ;;
  *)
    printf 'Unknown gate lane: %s\n\n' "$1" >&2
    usage >&2
    exit 2
    ;;
esac
