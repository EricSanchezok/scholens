ARG PYTHON_IMAGE=python:3.12.14-alpine3.23@sha256:aa81c9c4cc2f42592a6c8a9fba3a13838d9372e81e86030bf73132d5b8c5e4e8
ARG RDS_GLOBAL_BUNDLE_URL=https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
ARG RDS_GLOBAL_BUNDLE_SHA256=e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
FROM ${PYTHON_IMAGE} AS builder

ARG RDS_GLOBAL_BUNDLE_URL
ARG RDS_GLOBAL_BUNDLE_SHA256
ARG SANCHEZCLOUD_IDENTITY_REVISION
ARG SANCHEZCLOUD_IDENTITY_ARCHIVE=https://api.github.com/repos/EricSanchezok/sanchezcloud-identity/tarball
ARG SCHOLENS_EMBEDDING_MODEL_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3

RUN apk add --no-cache build-base ca-certificates curl curl-dev \
        "sqlite-libs>=3.53.2-r0" \
    && python -m pip install --no-cache-dir uv==0.9.2

WORKDIR /app
RUN --mount=type=secret,id=github_token \
    printf '%s' "${SANCHEZCLOUD_IDENTITY_REVISION}" | grep -Eq '^[0-9a-f]{40}$' \
    && mkdir -p /app/sanchezcloud-identity \
    && curl --fail --location --silent --show-error \
        --header "Authorization: Bearer $(tr -d '\n' </run/secrets/github_token)" \
        --header "X-GitHub-Api-Version: 2022-11-28" \
        --output /tmp/sanchezcloud-identity.tar.gz \
        "${SANCHEZCLOUD_IDENTITY_ARCHIVE}/${SANCHEZCLOUD_IDENTITY_REVISION}" \
    && tar -xzf /tmp/sanchezcloud-identity.tar.gz --strip-components=1 -C /app/sanchezcloud-identity \
    && rm /tmp/sanchezcloud-identity.tar.gz

RUN curl --fail --location --silent --show-error \
      --output /tmp/global-bundle.pem "${RDS_GLOBAL_BUNDLE_URL}" \
    && echo "${RDS_GLOBAL_BUNDLE_SHA256}  /tmp/global-bundle.pem" | sha256sum -c

COPY packages/scholens_observability/ /packages/scholens_observability/
COPY packages/scholens_ai/ /packages/scholens_ai/
COPY packages/scholens_job_contracts/ /packages/scholens_job_contracts/
COPY packages/scholens_runtime_contracts/ /packages/scholens_runtime_contracts/
COPY server/pyproject.toml server/uv.lock server/README.md /app/
RUN uv sync --frozen --no-dev --no-install-project \
        --no-install-package sanchezcloud-identity \
        --no-install-package onnxruntime \
    && uv pip install --no-deps /app/sanchezcloud-identity/
RUN .venv/bin/python -m scholens_ai.download_embeddings /app/models/search \
        --revision "${SCHOLENS_EMBEDDING_MODEL_REVISION}"

COPY server/app/ /app/app/
COPY server/migrations/ /app/migrations/
COPY server/alembic.ini server/gunicorn.config.py /app/
RUN uv pip install --no-deps /app

FROM ${PYTHON_IMAGE} AS runtime

RUN apk add --no-cache ca-certificates libcurl py3-onnxruntime \
        "openssl>=3.5.8-r0" \
        "sqlite-libs>=3.53.2-r0" \
    && adduser -D -u 1000 scholens

WORKDIR /app
COPY --from=builder /app/.venv/ /app/.venv/
COPY --from=builder /app/app/ /app/app/
COPY --from=builder /app/migrations/ /app/migrations/
COPY --from=builder /app/models/ /app/models/
COPY --from=builder /app/alembic.ini /app/gunicorn.config.py /app/
COPY --from=builder /tmp/global-bundle.pem /etc/ssl/certs/global-bundle.pem

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/usr/lib/python3.12/site-packages \
    SCHOLENS_EMBEDDING_MODEL_PATH=/app/models/search \
    SCHOLENS_SERVER_ROOT=/app \
    ENVIRONMENT=production \
    PORT=8000

USER scholens
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=3)"

ENTRYPOINT ["python", "-m", "app.bootstrap.runtime_entrypoint"]
CMD ["api"]
