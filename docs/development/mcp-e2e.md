# Local MCP E2E runbook (PR4)

The local wire-level E2E harness is the zero-deployment regression proof for
the MCP error-envelope fix: it drives the live `/mcp` endpoint with a strict
JSON-Schema-validating client (the ajv-equivalent behaviour of the TypeScript
SDK) and asserts that **no tool response is masked by a client-side `-32602`
schema rejection**. Every call must return either a success result or a
structured error carrying a real business error code.

This runbook is the reproducible procedure behind the `scripts/local_mcp_e2e.*`
harness. Run it on an already-provisioned local checkout; it never touches
production.

## What it verifies

- `tools/list` advertises exactly 56 tools, each with an `outputSchema` that
  accepts both the success envelope and the structured error envelope.
- The full tool matrix (read-only baseline, project lifecycle, paper metadata,
  annotation lifecycle, research outputs, jobs, ingestion validation paths,
  confirmation flows) returns either a success result or an `isError` result
  whose `structuredContent` **passes** the advertised `outputSchema`.
- The PR2 regressions are exercised end-to-end:
  - `create_annotation_thread` with an exact quote anchor succeeds;
  - a quote that does not exist in the paper is rejected with
    `annotation_quote_mismatch`;
  - offsets that do not cover the quote are rejected with
    `annotation_quote_mismatch`.
- Error paths that were previously masked in production (fake UUIDs, invalid
  tokens, invalid upload preparation, `annotation_thread` kind on
  `list_research_outputs`) now surface real error codes such as
  `project_not_found`, `project_invitation_invalid`, `library_paper_not_found`,
  `job_not_found`, `tool_arguments_invalid`, `public_paper_not_found`.

## Prerequisites

1. Local infrastructure up (PostgreSQL `127.0.0.1:55432`, Redis `56379`):
   ```bash
   docker compose -f jobs/compose.local.yaml up -d postgres redis
   ```
2. Server venv provisioned:
   ```bash
   cd server && uv sync --frozen --group dev --python 3.12
   ```
3. Local database migrated (see `DEVELOPMENT.md`; `auth` via
   `sanchezcloud-identity migrate`, `scholens` via `scholens db upgrade`).
4. A local test user and an Access Key:
   - create a user row in `auth.users` (or via the auth API),
   - bootstrap the operator admin: `scholens users bootstrap-admin --email ...`,
   - insert an Access Key for that user (permissions
     `read, write, manage, delete`) with a known `sk_scholens_...` secret and
     its SHA-256 hash in `scholens.access_keys`.
5. Start the local server (placeholder AI keys are sufficient; no LLM call is
   made by the matrix):
   ```bash
   cd server
   DATABASE_URL=... AUTH_DATABASE_URL=... AUTH_JWT_SECRET=... \
     SCHOLENS_AI_DEEPSEEK_API_KEY=local SCHOLENS_AI_MOONSHOTAI_API_KEY=local \
     uv run --frozen --no-sync scholens serve
   ```
   The server must listen on `127.0.0.1:7301`.

## Running the matrix

```bash
SCHOLENS_ACCESS_KEY=sk_scholens_... ./scripts/local_mcp_e2e.sh
```

or directly:

```bash
SCHOLENS_ACCESS_KEY=sk_scholens_... \
  server/.venv/bin/python scripts/local_mcp_e2e.py
```

Exit code `0` means: no masked responses, no transport failures, every
expected-success call succeeded and every expected-error call returned a
structured error with a real code. The script prints one line per case with a
`ok` / `err` / `MASK` / `FAIL` marker:

- `ok` — success result validated against the advertised `outputSchema`.
- `err` — structured error (`isError`) validated against the advertised
  `outputSchema`, with the business error code.
- `MASK` — `structuredContent` failed the advertised `outputSchema`
  validation: this replicates the production `-32602` masking and is a
  regression.
- `FAIL` — transport/JSON-RPC failure or an expectation violation (e.g. an
  expected error returned success).

## Classification rule

Per the Blueprint: a tool is usable when it returns a success result **or** a
structured error with a real error code. A masked response (`MASK`) is a
defect and fails the harness.

## Interpreting results

- `masked=0` and `failure=0` is the pass condition.
- `err` lines with business codes (`project_not_found`, `job_not_found`, ...)
  are the expected, correct behaviour for invalid inputs — they prove the
  error envelope is visible to strict clients.

## When to re-run

- After any change to `server/app/transport/mcp/` (schema generation,
  authentication, envelope serialization).
- After any change to tool input/output models or handler error paths in
  `server/app/tooling/`.
- After any change to `server/contracts/mcp-v1.json` or the contract export
  pipeline.
- Before merging any PR that touches MCP tool behaviour.
