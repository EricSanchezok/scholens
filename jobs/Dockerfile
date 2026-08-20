ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134
ARG RUNTIME_IMAGE=gcr.io/distroless/python3-debian12:nonroot@sha256:7d1042ce588ab97019fe95c24ffca7bc5a82ccdac572511d5e09bda4435c89c5
ARG SCHOLENS_EMBEDDING_MODEL_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3
FROM ${PYTHON_IMAGE} AS python-runtime

RUN rm -rf /usr/local/bin/pip* \
    /usr/local/lib/python3.12/ensurepip \
    /usr/local/lib/python3.12/site-packages/pip*

FROM ${PYTHON_IMAGE} AS builder

ARG SCHOLENS_EMBEDDING_MODEL_REVISION

RUN python -m pip install --no-cache-dir uv==0.9.2
WORKDIR /app
COPY packages/scholens_observability/ /packages/scholens_observability/
COPY packages/scholens_ai/ /packages/scholens_ai/
COPY packages/scholens_job_contracts/ /packages/scholens_job_contracts/
COPY packages/scholens_runtime_contracts/ /packages/scholens_runtime_contracts/
COPY jobs/pyproject.toml jobs/uv.lock jobs/README.md /app/
RUN uv sync --frozen --no-dev --no-install-project
RUN .venv/bin/python -m scholens_ai.download_embeddings /app/models/search \
        --revision "${SCHOLENS_EMBEDDING_MODEL_REVISION}"
COPY jobs/src/ /app/src/
RUN uv pip install --no-deps /app

FROM ${RUNTIME_IMAGE} AS runtime

WORKDIR /app
COPY --from=python-runtime /usr/local/ /usr/local/
COPY --from=builder /app/.venv/ /app/.venv/
COPY --from=builder /app/src/ /app/src/
COPY --from=builder /app/models/ /app/models/

ENV PATH=/app/.venv/bin:/usr/local/bin \
    SCHOLENS_EMBEDDING_MODEL_PATH=/app/models/search
USER nonroot:nonroot
EXPOSE 8001

ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8001"]
