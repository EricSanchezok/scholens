# 0024 — Shared Aliyun account and durable product email

Status: Accepted
Date: 2026-08-16
Owners: Scholens

## Problem

Scholens identity messages already use Aliyun DirectMail through
`sanchezcloud-identity`, while inherited legacy code sent unrelated product,
billing, onboarding, and invitation templates synchronously through Resend.
That split duplicated provider configuration, left dead templates, and allowed a
Project invitation transaction to succeed even when its best-effort email failed.
Identity security messages and product collaboration messages also have different
ownership and recovery requirements, so one application interface would blur the
boundary even if both used the same provider account.

## Decision

Scholens uses one product-specific Aliyun DirectMail account configuration and
`CLIENT_DOMAIN` for all Scholens links. Identity verification and password reset
remain entirely owned by the `sanchezcloud-identity` sender and templates.
Scholens Server owns a separate provider-neutral asynchronous transactional-email
interface for product messages; Aliyun is its first adapter.

Project invitations are the first product-email consumer. Their table directly
owns pending, sent, and failed delivery state plus bounded attempts, next-attempt
time, leases, safe failure code, and delivery time. Creation and queueing are one
transaction. The Server lifespan claims work in short transactions, calls the
provider outside the transaction, uses exponential retry, and recovers expired
leases across replicas.

The database never stores an invitation bearer token. An independent deployment
secret signs `{invitation_id, revision}`. Automatic delivery retry keeps the
revision; manual resend increments it and invalidates prior links.

Resend, its configuration aliases, legacy templates, onboarding profile mail,
task-completion mail, and billing email ports are removed rather than adapted.

## Alternatives considered

- Keep Resend for product mail: rejected because it maintains a second provider
  and operational contract without a launch requirement.
- Reuse the identity sender interface: rejected because identity templates and
  security semantics belong to `sanchezcloud-identity`, while product delivery
  needs durable application state and recovery.
- Send invitations in the HTTP request or a generic task payload: rejected
  because provider latency would delay the API and a task payload would either
  persist a bearer token or require a second source of delivery truth.
- Preserve old environment aliases and templates: rejected under the pre-release
  reset-first policy.

## Consequences

The mail secret contains only Aliyun credentials, while alias/reply policy stays
in task configuration and the invitation signing key stays in the core secret.
API replicas can recover delivery independently without duplicate processing of
one attempt. The Web can show truthful pending, sent, and failed states and offer
manual recovery. Future product messages may reuse the provider-neutral sender,
but each durable workflow must define its own user intent, persistence, and retry
contract; this decision does not create a speculative generic notification queue.

## Validation

Server tests cover message escaping, equivalent HTML/text links, Aliyun request
timeouts and retry classification, token tampering and revisions, lease claims,
retry outcomes, and invitation acceptance errors. Deployment checks reject old
Resend and identity-prefixed mail variables. Web Storybook and Playwright cover
collaborator delivery states and the invitation acceptance path.
