# 0029 — Detachable Conversation generation

Status: Accepted
Date: 2026-08-20
Owners: Scholens

## Problem

Conversation generation ran inside the HTTP SSE request. Mobile browsers pause
or destroy background pages, route changes unmount the subscriber, and ordinary
network loss closes the request. Each of those client lifecycle events therefore
cancelled accepted model work. Separately, provider exceptions wrapped by
Pydantic AI collapsed into a generic public error, so a diagnostic ID existed
without a durable safe classification after refresh.

Generation may execute model and tool operations and is not generally safe to
restart from the beginning. The browser must be able to detach and resume without
duplicating a Turn, tool mutation, token settlement, or response variant.

## Decision

The Server owns every asynchronously accepted Conversation response:

- A client requests `Prefer: respond-async`. One transaction creates the running
  Turn/Response, DurableJob, and outbox dispatch. The Response ID is also the job
  ID and concurrency-member identity.
- A dedicated Server-image Celery worker consumes only the `conversation` SQS
  queue. General Jobs workers explicitly exclude that Server-owned queue.
- PostgreSQL owns running and terminal Response state. Redis Streams retain a
  bounded 24-hour sanitized event replay log, addressed by SSE event ID, but are
  never canonical.
- The subscriber reconnects with `Last-Event-ID`; route change, page unmount,
  mobile backgrounding, reload, and offline intervals stop only that subscriber.
- Explicit Stop calls an authorized cancellation endpoint that conditionally
  transitions both Response and DurableJob. Disconnect is not cancellation.
- Completed, failed, and cancelled transitions are compare-and-set from
  `running`, so late model output cannot resurrect a cancelled response.
- An expired Conversation worker lease fails the attempt as
  `generation_interrupted`; it does not replay a partially executed model/tool
  sequence. ECS task protection reduces, but does not replace, this recovery
  boundary.
- Safe failure code, kind, retryability, diagnostic ID, and correlation ID are
  stored on the Response. Exception text, provider bodies, prompts, tool
  arguments, and tool results remain private diagnostics.
- The existing inline `200 text/event-stream` endpoint remains a compatible
  fallback during rollout. The new contract is additive.

## Alternatives considered

- **Keep request-owned SSE and tune mobile/browser settings.** Rejected because
  browser suspension, navigation, proxies, and connectivity are outside the
  Server's control.
- **Automatically replay a response after worker loss.** Rejected because model
  calls and workspace tools can have external or committed effects; whole-turn
  replay is not idempotent.
- **Persist every delta in PostgreSQL.** Rejected because transient delivery
  would contend with the canonical Conversation aggregate. Redis may lose
  partial deltas without losing the final response.
- **Let the general Jobs service execute Conversation tasks.** Rejected because
  it does not own Server domain composition, authorization, or the in-product
  agent runtime.
- **Treat every disconnect as an explicit Stop.** Rejected because it recreates
  the mobile failure and confuses transport loss with user intent.

## Consequences

- Accepted generation survives browser and route lifecycles and is recoverable
  from a fresh page using the running Response projection.
- Production gains a retained Conversation queue/DLQ, an on-demand ECS worker
  service, backlog scaling, task protection, logs, alarms, and dashboard metrics.
- The additive `conversation_responses.failure` JSONB column carries safe
  terminal metadata; existing rows and old applications remain valid.
- Partial live text may disappear if the replay cache is unavailable, but the
  subscriber still reconciles terminal state from PostgreSQL and the canonical
  completed answer is never lost.
- Cancellation is cooperative with at most the worker monitor interval before
  provider I/O is closed; the Response transition itself is immediate and
  authoritative.

## Validation

- Server tests cover stable wrapped-provider classification, running and failed
  response projection, cancellation/finalization compare-and-set behavior,
  queue ownership, terminal worker-lease recovery, the additive OpenAPI surface,
  and the dedicated runtime entrypoint.
- Web tests cover asynchronous acceptance, legacy fallback, event-ID reconnect,
  explicit cancellation, cancelled state, and SSE ID parsing. Storybook covers
  reconnecting and failed-stop disclosure on narrow and desktop surfaces.
- Deployment contracts and `cfn-lint` verify the queue, service, IAM, scaling,
  alarm, and immutable-image boundaries.
- Revisit replay retention or worker capacity when observed generation duration,
  queue age, or reconnect gaps exceed the documented limits.
