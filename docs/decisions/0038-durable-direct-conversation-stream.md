# 0038 — Durable direct Conversation streaming

Status: Accepted
Date: 2026-08-24
Owners: Scholens

Supersedes only ADR 0029's request-owned inline `200` compatibility path. Its
durable ownership, replay, cancellation, and recovery decisions remain accepted.

## Problem

Detachable Conversation generation made accepted work survive browser and
network lifecycles, but the two public submission modes still followed
different execution paths. The Web used `202` acceptance followed by a second
subscription request, while a caller without `Prefer: respond-async` ran the
agent inside the original HTTP request. A first Home prompt also created the
Conversation before accepting its Turn. Those extra boundaries delayed visible
feedback, retained request-owned cancellation semantics in one path, and made
the two modes harder to keep behaviorally identical.

On the browser, every provider fragment could publish a new React snapshot.
Accumulated Markdown was reparsed while Home or Reader ancestors and historical
messages rendered again. Adopting another chat framework solely to hide that
work would create a second state and protocol authority beside the existing
generated API, durable branch model, worklog, citation, and reconnect contracts.

## Decision

Every Conversation generation uses one Server-owned durable path:

- acceptance atomically persists the Turn, Response, DurableJob, and outbox
  dispatch before generation starts;
- a first prompt may atomically create its client-identified Conversation in
  the same command;
- `Prefer: respond-async` keeps the detachable `202` receipt, while the default
  response subscribes the same accepted generation directly as SSE;
- the established SSE media type retains its published event union, while a
  candidate-aware media type exposes durable cancellation and sanitized partial
  answer events without widening that compatibility boundary;
- disconnecting either subscriber never cancels generation; reconnect uses the
  existing Redis event ID and PostgreSQL terminal reconciliation;
- Redis remains a bounded sanitized replay log rather than canonical
  Conversation storage, and the transactional outbox remains the broker
  delivery boundary;
- production keeps at least two single-concurrency Conversation workers warm.

The Web keeps one feature-private live store. Incoming events update its target
state immediately, but React reads only a separately published snapshot.
Ordinary deltas are coalesced and published at a bounded cadence; terminal,
error, cancellation, and reset events publish immediately. Only the active
answer and its worklog subscribe to live slices. Durable server state continues
to use TanStack Query, navigation continues to use the URL, and the existing
academic Markdown renderer remains authoritative.

## Alternatives considered

- **Keep request-owned inline generation as the default.** Rejected because it
  duplicates execution and restores browser-lifecycle cancellation to an
  otherwise detachable workflow.
- **Require every client to use a `202` plus a second GET.** Retained as an
  explicit compatibility mode, but rejected as the only path because it adds a
  round trip before the browser can receive accepted-stream feedback.
- **Adopt Vercel AI SDK, assistant-ui, or another chat state library.** Rejected
  because Scholens already owns a generated HTTP/SSE contract, durable response
  branches, reconnect cursors, worklog items, validated citations, and explicit
  cancellation. Adapters would duplicate authority without removing the
  product-specific runtime.
- **Animate or type out an already buffered answer.** Rejected because it hides
  latency, delays useful content, and creates different reduced-motion behavior.
- **Replace the Markdown renderer or virtualize all history immediately.**
  Rejected as premature. Bounded publication and subscription isolation address
  the measured hot path without adding a second content pipeline.

## Consequences

- Direct and detachable clients observe one generation implementation and one
  terminal-state contract.
- First-prompt acceptance no longer requires an independently committed empty
  Conversation.
- The browser performs fewer React commits and cumulative Markdown parses while
  preserving complete target state and immediate terminal delivery.
- A process-local outbox wakeup reduces normal dispatch latency, while polling
  remains the cross-process and failure-recovery fallback.
- Enabled production releases switch compatible APIs and workers before Web on
  deploy, and Web before APIs and workers on rollback. If final verification of
  a forward release fails, recovery keeps the compatibility-tested candidate
  backend while restoring the previous Web so already-loaded browser tabs keep
  a valid stream contract.
- The live store and direct subscription require deterministic burst, hidden
  tab, disconnect, replay, and terminal-event tests.
- This decision does not change model choice, tools, context, answer budgets,
  citation validation, branching semantics, or explicit Stop behavior.

## Validation

- Server tests cover atomic and idempotent first-start acceptance, conflicting
  identities, durable direct SSE, detachable `202`, outbox wake/fallback, Redis
  replay, and candidate safety boundaries.
- Web tests cover publication cadence, target-state isolation, immediate
  terminal events, optimistic submission, reconnect behavior, and render
  boundaries.
- Production and browser telemetry measure queue age plus feedback, acceptance,
  first event, first visible content, ready time, and maximum stream stall
  without recording user, Conversation, or content identifiers.
