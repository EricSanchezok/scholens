ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134
FROM ${PYTHON_IMAGE} AS builder

RUN python -m pip install --no-cache-dir uv==0.9.2
WORKDIR /app
COPY packages/scholens_observability/ /packages/scholens_observability/
COPY packages/scholens_ai/ /packages/scholens_ai/
COPY packages/scholens_job_contracts/ /packages/scholens_job_contracts/
COPY packages/scholens_runtime_contracts/ /packages/scholens_runtime_contracts/
COPY jobs/pyproject.toml jobs/uv.lock jobs/README.md /app/
RUN uv sync --frozen --no-dev --no-install-project
COPY jobs/src/ /app/src/
RUN uv pip install --no-deps /app

FROM ${PYTHON_IMAGE} AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 scholens

WORKDIR /app
COPY --from=builder /app/.venv/ /app/.venv/
COPY --from=builder /app/src/ /app/src/

ENV PATH=/app/.venv/bin:$PATH
USER scholens
EXPOSE 8001

CMD ["python", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8001"]
