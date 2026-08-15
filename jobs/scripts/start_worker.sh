#!/usr/bin/env bash
set -euo pipefail

# Start Celery worker with health monitoring
echo "Starting Celery worker..."
jobs_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_bin="${SCHOLENS_JOBS_PYTHON:-$jobs_root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
    echo "Jobs virtual environment is missing; run 'uv sync --frozen --group dev'." >&2
    exit 1
fi
cd "$jobs_root"
queue_names=$("$python_bin" -m scholens_job_contracts)

# Set worker configuration
export CELERY_WORKER_AUTOSCALE="4,1"  # Max 4 concurrent tasks, min 1
export CELERY_WORKER_MAX_MEMORY_PER_CHILD="500000"  # 500MB

# Start worker with additional flags
exec "$python_bin" -m celery --app src.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues="$queue_names" \
    --max-tasks-per-child=1000 \
    --without-gossip \
    --without-mingle \
    --without-heartbeat
