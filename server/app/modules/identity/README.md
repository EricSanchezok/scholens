# Scholens authentication

Scholens embeds the shared
[`sanchezcloud-identity`](https://github.com/EricSanchezok/sanchezcloud-identity) Python SDK. It
does not maintain a second user table or login session. Cross-product onboarding, database-role,
upgrade, and troubleshooting rules are canonical in the
[Identity engineering handbook](https://github.com/EricSanchezok/sanchezcloud-identity/blob/main/docs/README.md).

## Identity boundary

- Canonical identities live in `auth.users` and use `BIGINT` IDs.
- Scholens-owned settings live in `scholens.user_profiles` and reference `auth.users.id`.
- Every Scholens user-owned table references `auth.users.id` directly.
- Access and refresh tokens are scoped to the `scholens` client through their
  JWT audience and refresh-token `client_id`.
- Zotero OAuth only connects a library to an authenticated user; it is not a
  login provider.

## HTTP API

The sanchezcloud-identity routers are mounted by the bootstrap composition root:

- `/api/v1/auth/*`: register, verify email, login, refresh, logout, password reset
- `/api/v1/auth/bootstrap`: rotate the browser refresh session and return the
  access token plus the product-enriched Actor in one additive response
- `/api/v1/me/profile`: shared identity profile operations
- `/api/v1/me`: shared identity enriched with Scholens profile state
- `/api/v1/me/avatar`: short-lived read-only view of the caller's private shared avatar

Authorized Project-member and annotation-list HTTP responses may carry the same
short-lived avatar view for identities already visible through that product
operation. Avatar presentation remains at the HTTP boundary: Actor, canonical
application operation responses, MCP, jobs, and persistent Scholens records never
carry the URL or object key. Missing or unavailable avatars fall back to initials
without failing those product reads.

Protected endpoints require `Authorization: Bearer <access-token>`. Scholens
keeps access tokens in browser memory. Refresh tokens are rotated in the
host-only `scholens_refresh` cookie with `HttpOnly`, `SameSite=Strict`, and
`Secure` enabled in production; JavaScript never receives them.

Bootstrap is a Scholens application workflow: the sanchezcloud-identity adapter
validates the refresh subject, product access is resolved before rotation, and
the adapter then atomically rotates the shared session. This ordering prevents
a downstream profile failure from consuming a refresh token without returning
its successor cookie. Existing `/auth/refresh` and `/me` contracts remain
independently callable.

## Required configuration

Identity host settings use the `AUTH_` prefix. Production must provide at least:

```dotenv
AUTH_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
AUTH_JWT_SECRET=replace-with-a-long-random-secret
SHARED_AVATAR_BUCKET=sanchezcloud-account-avatars-ACCOUNT-REGION
SHARED_AVATAR_URL_TTL_SECONDS=900
SHARED_AVATAR_CACHE_MAX_ENTRIES=2048
SHARED_AVATAR_CACHE_REFRESH_SKEW_SECONDS=60
SHARED_AVATAR_MISSING_CACHE_TTL_SECONDS=60
CLIENT_DOMAIN=https://scholens.example.com
SCHOLENS_ALIYUN_DM_ACCESS_KEY_ID=...
SCHOLENS_ALIYUN_DM_ACCESS_KEY_SECRET=...
SCHOLENS_ALIYUN_DM_ACCOUNT_NAME=...
SCHOLENS_ALIYUN_DM_FROM_ALIAS=Scholens
```

The token audience is fixed to `scholens` in application code and is not an
environment override.

Production requires the shared avatar bucket. The API role has read-only object
and KMS decrypt access scoped to `auth/avatars/v1/*`; it has no avatar upload or
Identity-table mutation capability. Local development leaves the bucket empty
and uses initials unless a non-production shared bucket is deliberately supplied.

`AUTH_DATABASE_URL` defaults to `DATABASE_URL`, so the synchronous Scholens
ORM and the asynchronous sanchezcloud-identity pool can share one RDS database.

Run sanchezcloud-identity migrations independently before Scholens migrations. Scholens
only checks the installed auth schema version and never carries or executes
sanchezcloud-identity migration files.
