# 0036 — Validated Conversation final output

Status: Superseded by [ADR 0044](./0044-text-terminal-conversation-harness.md)
Date: 2026-08-22
Owners: Scholens
Supersedes in part: [ADR 0008](./0008-single-conversation-agent.md)

## Problem

ADR 0008 let any model response without a tool call terminate the Conversation
agent as plain text. The harness streamed that text before it knew whether the
node was progress or final and accepted any non-empty value. A production run
therefore persisted internal planning and private citation instructions as a
completed answer. Invalid tool arguments also returned a generic tool result,
so the model could not reliably correct a declared-schema mismatch.

The public event contract must still support direct answers, progress before
tools, validated citations, and one model/tool loop without exposing provider
reasoning or adding a second synthesis model call.

## Decision

- Conversation generation has one structured output tool,
  `final_answer`, whose internal result is `FinalAnswer { answer: string }`.
  Plain model text cannot terminate a run.
- Model text is buffered until its complete response node is known. Text that
  accompanies an ordinary runtime tool call may become bounded progress;
  output-tool preambles, invalid drafts, and plain-text terminal attempts are
  never emitted.
- The structured answer is validated before public deltas or persistence.
  Empty visible output, citation-only output, and copied private citation
  protocol receive a bounded model retry. Once a successful source-backed tool
  has registered validated source keys, the answer must also materialize at
  least one valid private citation; missing references, malformed markers, and
  unknown keys are retried before any final text is published. Visible model
  placeholders such as `[A1]` are rejected rather than persisted as fake source
  controls. Retry exhaustion becomes the existing invalid-provider-response
  failure path.
- Validation and publication reuse one completed grounded-answer inspection, so
  the private protocol is not parsed twice with independently drifting results.
  Low-cardinality telemetry records retry reasons and accepted available-source,
  used-source, and annotation counts.
- A local tool argument validation error raises `ModelRetry` with sanitized
  field locations, error types, and messages. Raw arguments remain private;
  non-validation business failures remain ordinary safe tool results.
- Public HTTP and SSE event shapes do not change. A validated final answer may
  arrive as one buffered delta rather than provisional token-by-token text.

## Alternatives considered

- **Keep `str` output and detect unfinished prose.** Rejected because language
  heuristics cannot distinguish planning from a legitimate answer reliably.
- **Run a second model call to judge or rewrite every answer.** Rejected because
  it adds latency, cost, and another independently fallible synthesis path.
- **Expose validation inputs or raw tool arguments.** Rejected because repair
  needs only the declared schema and sanitized field errors.

## Consequences

Final-answer latency includes validation before the first visible final delta,
while tool activity and classified progress remain visible. Direct answers and
tool-backed answers share one explicit completion boundary. A direct answer is
not forced to cite merely because its starting context contains papers; the
additional reference invariant begins only after a successful tool call returns
validated source material. Tests and model harnesses must submit `final_answer`;
a provider that cannot produce the declared tool output is unsupported for
Conversation generation.

The stronger invariant is forward-only. Existing persisted answers without a
validated `ReferenceBundle` are not rewritten, stripped, or assigned guessed
sources because their visible labels do not prove an evidence mapping. The
existing response-regeneration action is the recovery path for those variants.

## Validation

Server tests cover plain-text retries, private-protocol rejection, citation-only
rejection, missing source-backed references, valid direct and grounded answers,
safe tool-argument correction, retry exhaustion, and the unchanged typed public
event sequence.
