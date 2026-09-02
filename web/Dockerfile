ARG NODE_IMAGE=node:22.23-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32

FROM ${NODE_IMAGE} AS dependencies
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.11.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM dependencies AS build
ARG RELEASE_SHA
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_ACCOUNT_CENTER_URL=https://myaccount.sanchezcloud.net
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_RELEASE_SHA=${RELEASE_SHA} \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_ACCOUNT_CENTER_URL=${NEXT_PUBLIC_ACCOUNT_CENTER_URL}
COPY . .
RUN test -n "$NEXT_PUBLIC_API_URL" \
    && echo "$NEXT_PUBLIC_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$' \
    && pnpm build \
    && pnpm pdfjs:assets:check \
    && node scripts/package-source-maps.mjs

FROM ${NODE_IMAGE} AS runtime
RUN apk add --no-cache "openssl>=3.5.8-r0"
WORKDIR /app
ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
RUN find . -type f -name '*.map' -delete
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/healthz || exit 1
# Docker and ECS inject their own HOSTNAME at container start, overriding the
# image ENV. Pin the Next.js bind address for the child process so the loopback
# health check and awsvpc target can both reach the standalone server.
CMD ["sh", "-c", "HOSTNAME=0.0.0.0 exec node server.js"]

FROM scratch AS source-maps
COPY --from=build /tmp/scholens-source-maps/ /
