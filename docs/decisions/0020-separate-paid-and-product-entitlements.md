# 0020 — Separate paid subscriptions from product-granted entitlements

Status: Accepted
Date: 2026-08-16
Owners: Scholens

## Problem

Scholens needs to give internal researchers and selected testers the same
high-capacity experience as a paid Researcher without creating fictitious
Stripe state. It also needs temporary, exact quota boundaries for development
and test work. Direct SQL edits to subscriptions or product resources erase
the distinction between payment facts and operator intent, bypass application
invariants, and leave incomplete attribution.

Entitlement resolution must remain safe when a paid subscription and an
internal grant overlap. Expiration or revocation of the internal grant must not
downgrade a user whose paid Researcher subscription remains active.

## Decision

Stripe-backed `subscriptions` remains the sole payment record. Scholens owns
two independent product records:

- `account_plan_grants` grants an expiring Researcher entitlement and records
  the target, granting administrator, reason, grant time, expiry, and optional
  revocation;
- `account_quota_overrides` replaces one named numerical limit for an expiring
  test window and records equivalent attribution.

The effective plan is the highest active entitlement from payment and product
grant. Active numerical overrides are applied afterward to the resolved plan's
limits. Expired and revoked records remain historical but no longer influence
resolution. Entitlement loss never deletes existing research; capacity checks
only prevent additional resources or AI usage.

Operator mutations run through the application service and Unit of Work via
the private `scholens` CLI. A `CliOrigin` stores the normalized command name and
an invocation UUID in the append-only Operation Journal. No public
administrator API is introduced, and SQLAdmin business views are read-only.
Entitlement reasons remain on the entitlement records. Identity admin/block
commands do not collect arbitrary reason prose that the Journal contract would
discard; explicit confirmation provides acknowledgement, while action, actor,
resource, command name, and invocation UUID remain durable.

Account capacity and entitlement writes share a billing-owned two-int advisory
lock (`BILL`, user ID). Batch targets are locked in stable user-ID order and
their AuthUser/UserProfile facts are re-read before mutation. Privileged CLI
authorization similarly holds the administrator-roster lock followed by the
actor rows for the whole Unit of Work; revoke/block follows that same order.

Because Journal rows cannot be rewritten or deleted, the migration's `cli`
origin vocabulary is a one-way compatibility extension: downgrading the
entitlement tables intentionally retains `cli` in the origin check constraint
so historical audit rows remain valid.

## Alternatives considered

- **Create synthetic Stripe subscriptions.** Rejected because it corrupts the
  meaning of payment state and can trigger billing lifecycle behavior for a
  grant that was never purchased.
- **Add plan/admin flags to `auth.users`.** Rejected because Identity is shared
  infrastructure and must not own product roles, payment, or Scholens quota.
- **Use permanent per-user limits only.** Rejected because ordinary internal
  access needs a coherent Researcher plan while boundary tests need temporary,
  narrowly scoped replacements, including zero.
- **Continue direct SQL and editable SQLAdmin views.** Rejected because they
  bypass validation, last-admin safeguards, transaction boundaries, and
  durable operation attribution.
- **Expose a remote admin HTTP API.** Rejected because current operations run
  inside the Server container or an SSM session and do not justify another
  public attack surface.

## Consequences

Paid and internal access can overlap safely, and both automatically fall back
when their own validity ends. Operators must supply an exact actor and
confirmation for business writes; entitlement and quota mutations also require
a persisted reason. Automation uses explicit `--yes` and stable JSON/exit codes.
Grant and override tables need migrations, constraints,
expiry-aware queries, idempotent commands, and concurrency serialization.

The CLI deliberately cannot reset Token usage, rewrite Stripe subscriptions,
arbitrarily retry or mutate jobs, or reset a non-local database. Model-provider
configuration, BYOK, Coding Plans, price tables, and model-weighted credits are
outside this decision.

## Validation

Domain and application tests cover paid/granted precedence, expiry,
revocation, zero-valued overrides, idempotence, batch prevalidation, and
last-administrator protection. CI applies the incremental product migration
twice, performs a real downgrade with existing CLI Journal rows, exercises
grant/override commands, and runs the guarded local reset while asserting that
`auth` is unchanged.
