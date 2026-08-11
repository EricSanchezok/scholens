# 0010 — Turn suggestions and two-stage response readiness

Status: Accepted
Date: 2026-08-11
Owners: Scholens

## Context

The old client waited for answer persistence, synchronous title generation, a
second suggestion request, and a turn refetch before showing response actions.
This made a finished answer look unfinished and coupled optional enrichment to
the critical interaction path. Suggestions were also response-owned even
though retries ask the same next-question intents.

## Decision

Suggestions belong to `ConversationTurn` and are generated as a non-critical
sidecar in parallel with the answer. The allowlisted prompt contains only the
current query, locale, three recent selected turns, and authorized scope display
titles, capped at 12,000 characters. It excludes the current answer, tool
traces, raw tool results, and document bodies.

The public typed SSE has two finalization stages:

- `response_ready` carries the complete persisted `ConversationTurnResponse`
  snapshot and immediately enables answer actions and another submission;
- an optional `suggestions` event updates that turn when the sidecar finishes;
- `complete` means no more stream events and carries only turn and response IDs.

The stream waits at most two seconds after `response_ready` for non-critical
sidecars. Failure and timeout are silent product states with diagnostics only.
Every suggestion write revalidates that its turn is still latest. Creating a
new turn clears the prior turn's suggestions and prunes unselected variants.
Retries reuse existing turn suggestions and may retry generation only when none
were persisted.

The first-title sidecar starts with the first accepted turn and never blocks
`response_ready`. Explicit titles continue to win at persistence time.

## Alternatives considered

- Generate suggestions after the final answer. Rejected because it serializes
  optional model latency behind the visible answer.
- Keep a second HTTP endpoint and poll. Rejected because it duplicates stream
  lifecycle state and makes stale writes and UI timing harder to reason about.
- Attach suggestions to each response variant. Rejected because retries do not
  change the user turn or the intended next-question set.
- Reserve skeleton rows. Rejected because optional enrichment should not make a
  ready answer appear incomplete.

## Consequences

The Web can render actions directly from the stream snapshot without a refetch.
Optional suggestions usually arrive with the answer and otherwise appear in a
bounded, non-blocking tail. Clients must ignore events whose turn/response IDs
no longer match the active stream. The old suggestion endpoint, statuses,
claim/finalize workflow, polling, and unavailable states no longer exist.

## Validation

Server tests prove sidecars start before answer completion, `response_ready`
follows persistence and precedes optional suggestions, timeouts do not fail the
answer, retries reuse turn data, and stale writes cannot update older turns.
Web tests cover immediate footer rendering, synchronous hiding of latest-only
controls on submit, late-event identity guards, retry variants, responsive
layouts, keyboard behavior, and reduced motion.
