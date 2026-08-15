# 0019 — User-owned integration credentials and explicit AI reflow

Status: Accepted
Date: 2026-08-15
Owners: Scholens
Refines: [ADR 0017](./0017-evidence-driven-reader-reflow.md)

## Problem

MinerU previously depended on one Jobs environment token. That made Scholens
the credential owner, coupled every user to one provider account, and allowed
PDF completion to trigger an expensive AI reflow the user had not requested.
It also left retries, credential replacement, and PDF rescue sharing ambiguous
failure behavior. A token placed directly into a Celery payload or retained by
Jobs would expand the secret's lifetime and make logs, exceptions, callbacks,
and telemetry harder to defend.

The existing connector CRUD represented a different ownership model and could
not safely express revision-bound credentials or a built-in provider. Scholens
is pre-release, so preserving that disposable contract would create permanent
dual paths without protecting released user data.

## Decision

Every optional provider credential is a user-owned `IntegrationConnection`
stored encrypted by Server. MinerU joins AnySearch, Tavily, Exa, and Firecrawl
on one `/api/v1/me/integrations` contract; Scholight is built in. Public
responses contain status, masked metadata, verification outcome, and credential
revision, never the stored secret. The previous connector routes, models, and
legacy UI are removed without compatibility aliases or backfill.

MinerU has no process-level API token. A PDF or reflow dispatch contains only a
signed internal credential URL. Jobs requests the currently enabled plaintext
and its revision only after it claims an eligible owner- and operation-scoped
job. Secrets are excluded from dataclass representations and may not appear in
task payloads, callbacks, logs, exceptions, operation journals, or telemetry.
Every provider outcome echoes the fetched revision, so Server ignores a stale
outcome after the user replaces the connection.

AI reflow is explicit. PDF completion never schedules it. Starting a new or
failed attempt preflights MinerU and uses an idempotency key; active and
completed artifacts remain accessible without a token. A failed attempt keeps
immutable job history and exposes another attempt rather than resetting the
previous Job. Attempt acceptance locks the stable parent `Document` row before
re-reading the reflow artifact or idempotency state. Concurrent first requests,
including requests with different client keys, therefore converge on one
Durable Job, dispatch outbox row, artifact, and Journal entry. A missing
artifact projects `not_requested` with no fabricated `updated_at`; only a
persisted artifact has an update timestamp.

PDF ingestion remains local-first. Scanned PDFs require MinerU, while MinerU is
only a rescue for digital PDFs after both local engines fail. If rescue is
unavailable, a digital document may complete with its deterministic text-only
fallback; a scanned document reports the required integration. Redis
checkpoints bind purpose, Document, and credential revision. Retryable transport
failures retain resumable provider state, while success and non-retryable
failure clear it.

Provider outcomes have stable meanings: credential required, credential
invalid, rate limited, unavailable, content insufficient, and response unsafe.
Only the first four are actionable or retryable as their semantics permit;
provider diagnostics remain internal.

## Alternatives considered

- Keep one deployment MinerU token. Rejected because it preserves shared
  ownership, prevents per-user replacement, and makes cost and provider status
  inseparable across accounts.
- Copy a user's token into every Celery payload. Rejected because brokers,
  result stores, retries, and task inspection would become secret-bearing
  systems.
- Let Jobs decrypt the integration table directly. Rejected because it breaks
  Server data ownership and cannot prove job, owner, operation, or revision
  scope at the access boundary.
- Automatically reflow every successfully parsed PDF. Rejected because reflow
  is an optional paid transformation and PDF ingestion is already a complete
  product outcome.
- Convert every MinerU failure into one retryable generic error. Rejected
  because credential repair, provider backoff, content limitations, and unsafe
  archives require materially different user actions.
- Preserve the connector endpoints as a compatibility facade. Rejected because
  the product is pre-release and the facade would create two competing
  credential authorities.

## Consequences

Server owns encryption, revision policy, public status, job-scoped secret
release, and replacement safety. Jobs owns short-lived provider use, resumable
revision-bound checkpoints, archive validation, and classified outcomes. Web
owns connection setup, explicit reflow initiation, actionable prompts, and
single-resume pending intents.

Deployments must set a strong `INTEGRATION_CREDENTIAL_ENCRYPTION_KEY`; Jobs must
not set a MinerU token. Reset-first migration rebuilds the Scholens schema on
this new contract while leaving the independently owned `auth` schema intact.
Losing the encryption key makes stored integrations unusable and requires users
to reconnect; key rotation is a deliberate future operation, not a dual-key
runtime path.

## Validation

Server tests cover encrypted persistence, secret-free projections, revision-
bound updates, signed job scope, reflow preflight, same-key and different-key
first-attempt serialization, nullable not-requested timestamps, idempotency,
and stale outcomes. Jobs tests cover secret-free representations and callbacks, local-
first fallback, revision-bound checkpoints, retry retention, archive safety,
and every stable MinerU error class. Web Storybook and interaction tests cover
all Settings panels, missing-token prompts, connection save, single resume,
reflow retry, ingestion fallback, mobile containment, themes, and locales.
