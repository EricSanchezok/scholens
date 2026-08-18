#!/usr/bin/env bash
# Local full-stack MCP E2E harness for the Scholens tool set (PR4).
#
# Verifies, against a real local stack (PostgreSQL 55432, Redis 56379,
# Server 7301), that every MCP tool returns either a success result or a
# structured error envelope (never a client-side -32602 schema rejection).
# This is the zero-deployment regression proof for the error-envelope fix.
#
# Usage:
#   SCHOLENS_ACCESS_KEY=sk_scholens_... ./scripts/local_mcp_e2e.sh
#
# Prerequisites (see DEVELOPMENT.md and docs/development/mcp-e2e.md):
#   - docker compose -f jobs/compose.local.yaml up -d redis
#   - PostgreSQL on 127.0.0.1:55432 (scholens_dev_postgres container)
#   - server/.env provisioned (DATABASE_URL, AUTH_JWT_SECRET, ...)
#   - server venv provisioned (uv sync --frozen --group dev --python 3.12)
#   - local server running on 7301:
#       cd server && uv run --frozen --no-sync scholens serve
#   - one Access Key for a local actor (see the runbook)
#
# The heavy lifting is done by scripts/local_mcp_e2e.py, which drives the
# live /mcp endpoint with a strict JSON-Schema-validating client.

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="$REPOSITORY_ROOT/server"
SERVER_URL="http://127.0.0.1:7301/mcp"

log() { printf '\033[1;34m[e2e]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[e2e][FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

log "Scholens local MCP E2E harness"
log "Repository: $REPOSITORY_ROOT"

# --- Environment checks -------------------------------------------------------
if [[ -z "${SCHOLENS_ACCESS_KEY:-}" ]]; then
  fail "SCHOLENS_ACCESS_KEY is required; create one with the operator CLI (see runbook)"
fi
if [[ ! -x "$SERVER_DIR/.venv/bin/python" ]]; then
  fail "server venv is missing; run: cd server && uv sync --frozen --group dev --python 3.12"
fi
if ! curl -s -o /dev/null --max-time 3 "$SERVER_URL"; then
  fail "local server is not reachable at $SERVER_URL; start it with 'scholens serve' first"
fi

log "Running the wire-level tool matrix against $SERVER_URL"
log "  (strict outputSchema validation, ajv-equivalent)"
set +e
SCHOLENS_ACCESS_KEY="$SCHOLENS_ACCESS_KEY" \
  "$SERVER_DIR/.venv/bin/python" "$REPOSITORY_ROOT/scripts/local_mcp_e2e.py"
STATUS=$?
set -e

if [[ $STATUS -ne 0 ]]; then
  fail "E2E matrix reported masked or failed responses"
fi
log "E2E matrix passed: every tool returns a success result or a structured error."
