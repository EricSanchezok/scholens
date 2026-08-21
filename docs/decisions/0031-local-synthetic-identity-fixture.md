# 0031 — Explicit local synthetic identity fixture

Status: Accepted
Date: 2026-08-21
Owners: Scholens

## Problem

Manual Scholens development needs a stable account with realistic Identity and
product state. Re-registering sends real verification mail, slows every fresh
local setup, and encourages developers to reuse personal addresses. A UI-only
"dev login" or a production-callable impersonation endpoint would bypass the
authentication path under test and create a dangerous deployment surface.

The shared local database is also consumed by Scholight and Account Center.
Identity continues to own credentials, verification, lockout, and refresh
sessions; Scholens must not introduce direct SQL that reimplements those rules.

## Decision

Provide an explicit, idempotent `scholens dev seed-test-account` operator
command. It runs only when all of these conditions hold: environment is exactly
`development`, the runtime role is `scholens_app`, PostgreSQL is exactly
`127.0.0.1:55432/sanchezcloud`, and the email uses an IANA-reserved synthetic
domain.

The command constructs a bounded one-connection SanchezCloud Identity SDK
adapter with mail delivery disabled. Registration, verification, password
hashing/reset, and session revocation use the SDK's public manager and database
interfaces. Scholens then resolves its owned product profile through the normal
application service. Optional administrator bootstrap remains the existing
first-admin-only operation. The command is never called by startup, migration,
the public HTTP API, or Web code.

Passwords come from a hidden prompt or the ignored local-only
`SCHOLENS_DEV_TEST_PASSWORD` environment value. No password is committed,
printed, logged, or returned in JSON. When an existing password already
matches, the command does not rotate its hash or revoke sessions.

## Alternatives considered

- Add a Web "login as developer" control and private HTTP endpoint. Rejected
  because it bypasses the real login boundary and risks production exposure.
- Commit a universal default password. Rejected because shared credentials
  become habitual and can leak into non-local environments.
- Insert or update `auth.users` directly from Scholens SQLAlchemy. Rejected
  because it duplicates Identity-owned password, verification, and session
  behavior.
- Keep manual registration and real verification email. Rejected because it is
  slow, non-deterministic, and encourages non-synthetic identities.
- Seed automatically during `serve` or `dev reset-product`. Rejected because
  daily startup must remain side-effect-free and product reset must not mutate
  the independently owned `auth` schema.

## Consequences

Developers run one explicit command and then exercise the same login, access
token, refresh cookie, profile creation, and authorization path used by real
accounts. The fixture is visible to every local product sharing `auth`, which is
intentional and documented. A password change revokes existing sessions, while
an unchanged rerun preserves them.

The command depends on the pinned Identity SDK's public fixture primitives and
must evolve with that dependency. It cannot repair a disabled or locked account;
the operator chooses another synthetic email rather than bypassing an Identity
security decision.

## Validation

Tests cover new-account verification, repeat idempotency, password/profile
repair, locked-account refusal, secret redaction, production refusal,
non-loopback database refusal, real-domain refusal, and normal login against the
seeded local identity.
