# 0038 — Validated provisional Conversation streaming

Status: Accepted
Date: 2026-08-23
Owners: Scholens
Supersedes in part: [ADR 0036](./0036-validated-conversation-final-output.md)

## Problem

ADR 0036 correctly made `final_answer` the only terminal model output, but it
coupled full output validation to first publication. The Server therefore held
the entire final answer and emitted it as one delta. This removed useful
token-by-token feedback, especially on mobile and on longer research answers.

Publishing raw output before validation would restore latency at the cost of
showing a draft that may need an output-validator retry. The protocol also has
deployed clients that reject unknown event discriminators, so a new retraction
event cannot be sent to every client during a rolling release.

## Decision

- The model still terminates through one structured `final_answer` tool and one
  model/tool run. Plain text remains non-terminal and there is no second
  synthesis call.
- While the provider streams the output-tool arguments, the Server partially
  validates the cumulative `FinalAnswer.answer` field and publishes its visible
  text as a provisional assistant item. Citation markers remain inside the
  existing stateful grounding parser, and a bounded holdback prevents private
  output-protocol terms from crossing the public boundary.
- Full schema and output-validator checks remain authoritative. Success
  completes the same stable item. A retry emits `assistant_item_discard` for an
  already visible candidate before the replacement attempt begins; discarded
  content is never persisted.
- Clients opt into provisional semantics with
  `Accept: text/event-stream; scholens-events=2`. The HTTP boundary buffers item
  start/delta frames for clients without that parameter, releases them only on
  item completion, and drops them on discard. Old clients therefore retain the
  ADR 0036 behavior during a rolling release.
- Conversation SSE responses disable transformation and proxy buffering with
  `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`, and vary
  by `Accept`.

## Alternatives considered

- **Return to unstructured text output.** Rejected because it reintroduces the
  planning-text and private-protocol failure that ADR 0036 fixed.
- **Validate with a second model before streaming.** Rejected because it adds a
  second latency, cost, and failure boundary and still cannot approve tokens
  before that call finishes.
- **Publish invalid drafts without retraction.** Rejected because retry output
  would concatenate with or visibly survive beside the accepted answer.
- **Send the new event to every client immediately.** Rejected because deployed
  Web clients intentionally fail closed on unknown event types.

## Consequences

New clients regain low first-token latency while completion and persistence
remain fully validated. A rare validator retry can briefly show a candidate
and then remove it; reducers must treat discard as idempotent and scoped to the
stable item ID. The compatibility adapter temporarily preserves buffered
delivery for old clients and can be removed only after the v1 event consumer is
outside the supported rollout window.

## Validation

Server tests require multiple visible deltas from one structured output,
candidate discard on full-validation retry, citation/protocol non-disclosure,
legacy buffering, and no-buffer response headers. Web tests cover the new
event parser and reducer behavior. The generated OpenAPI and TypeScript
contracts include the discard event.
