# 0036 — Validated Conversation final output

Status: Accepted
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
  protocol receive a bounded model retry. Retry exhaustion becomes the existing
  invalid-provider-response failure path.
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
tool-backed answers share one explicit completion boundary. Tests and model
harnesses must submit `final_answer`; a provider that cannot produce the
declared tool output is unsupported for Conversation generation.

## Validation

Server tests cover plain-text retries, private-protocol rejection, citation-only
rejection, valid direct and grounded answers, safe tool-argument correction,
retry exhaustion, and the unchanged typed public event sequence.
