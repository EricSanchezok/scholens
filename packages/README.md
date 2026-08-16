# Shared Python packages

This workspace owns Python code that is used by more than one Scholens
deployment unit. Server and Jobs remain independently deployable applications
with separate `pyproject.toml` files and lockfiles; this directory provides a
third, direct development and test environment for the shared code itself.

## Package admission

A new shared package is justified only when all of the following are true:

- at least one current Server or Jobs consumer needs the public contract;
- the responsibility is narrow, service-neutral, and named explicitly;
- the dependency direction remains `server|jobs -> package`, never the reverse;
- the package has a `src/` layout, `README.md`, `py.typed`, and direct tests;
- its consumer declarations and local `uv` sources are added together; and
- dependency changes are reflected in this workspace lock and both affected
  consumer lockfiles.

Do not move product authorization, persistence, transport, or workflow policy
into a package merely to deduplicate a few lines. Shared packages expose
stable primitives; each application owns its product composition.

## Current packages

| Package                                                        | Public import            | Current consumers | Responsibility                                                |
| -------------------------------------------------------------- | ------------------------ | ----------------- | ------------------------------------------------------------- |
| [`scholens-ai`](./scholens_ai/README.md)                       | `scholens_ai`            | Server, Jobs      | Provider-neutral AI workload profiles and model construction  |
| [`scholens-job-contracts`](./scholens_job_contracts/README.md) | `scholens_job_contracts` | Server, Jobs      | Queue names and callback timing/size limits                     |
| [`scholens-observability`](./scholens_observability/README.md) | `scholens_observability` | Server, Jobs      | Business-agnostic logs, metrics, traces, and safe diagnostics |
| [`scholens-runtime-contracts`](./scholens_runtime_contracts/README.md) | `scholens_runtime_contracts` | Server, Jobs | Managed cache and database endpoint validation          |

## Development

Create or refresh the dedicated environment explicitly when dependencies
change:

```bash
uv sync --directory packages --frozen --all-packages --group dev
```

Each checkout owns this environment. Recreate it from `packages/uv.lock` after
moving the repository or detecting a stale interpreter path instead of copying
`packages/.venv` from another worktree.

The quality gate itself is read-only with respect to dependencies:

```bash
packages/.venv/bin/python scripts/check_workspace.py
uv lock --check --directory packages
uv lock --check --directory server
uv lock --check --directory jobs
packages/.venv/bin/ruff format --check \
  packages/scholens_ai/src packages/scholens_ai/tests \
  packages/scholens_job_contracts/src packages/scholens_job_contracts/tests \
  packages/scholens_observability/src packages/scholens_observability/tests \
  packages/scholens_runtime_contracts/src packages/scholens_runtime_contracts/tests
packages/.venv/bin/ruff check \
  packages/scholens_ai/src packages/scholens_ai/tests \
  packages/scholens_job_contracts/src packages/scholens_job_contracts/tests \
  packages/scholens_observability/src packages/scholens_observability/tests \
  packages/scholens_runtime_contracts/src packages/scholens_runtime_contracts/tests
packages/.venv/bin/mypy --config-file packages/pyproject.toml \
  packages/scholens_ai/src packages/scholens_job_contracts/src \
  packages/scholens_observability/src packages/scholens_runtime_contracts/src
PYTHONPATH=packages/scholens_ai/src:packages/scholens_job_contracts/src:packages/scholens_observability/src:packages/scholens_runtime_contracts/src \
  packages/.venv/bin/pytest -q \
  packages/scholens_ai/tests packages/scholens_job_contracts/tests \
  packages/scholens_observability/tests packages/scholens_runtime_contracts/tests
```

Run the repository gate runner for the canonical command after it is available:

```bash
./scripts/run-gates.sh shared-packages
```
