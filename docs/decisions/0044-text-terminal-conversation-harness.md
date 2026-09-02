# ADR 0044: Plain-text terminal boundary for conversation harness

- Status: accepted
- Date: 2026-09-02
- Supersedes: the runtime decision in ADR 0036 to require a `final_answer`
  output tool

## Problem

The conversation worker used a model-visible `final_answer` output tool to
terminate a Pydantic AI run. That coupled model termination, citation
validation, candidate rendering, and answer publication. Reasoning-capable
providers can reject the forced output-tool request, and citation defects could
consume output retries even when safe prose was already available.

Research-agent demonstrates a safer boundary: the provider's ordinary text and
finish reason determine the terminal assistant message, while tool execution
and presentation remain separate concerns.

## Decision

Scholens keeps Pydantic AI's `Agent.iter()` model/tool loop and provider
adapters. The conversation Agent uses `output_type=str`; no finalization tool,
structured final-answer envelope, compatibility alias, or runtime feature flag
is retained.

The harness classifies complete model nodes by tool presence and normal
termination. Text accompanying a tool call is bounded progress. Ordinary text
with no tool call is the terminal answer. Citation markers are normalized only
after terminal classification through the server-owned source registry.

Citation defects are soft publication failures: invalid annotations are
dropped and safe prose completes with a typed citation summary. Empty visible
output, private protocol prose, stream corruption, and unexpected output tools
are hard failures. Tool argument schema errors may still use the existing
bounded Pydantic AI retry boundary.

Candidate events remain an additive public projection, but are produced from
classified terminal text rather than partial JSON output-tool arguments. Public
SSE/API/database contracts remain unchanged.

## Alternatives considered

- Keep `final_answer` and increase output retries: rejected because it preserves
  provider incompatibility and couples citation quality to termination.
- Add a second synthesis model call: rejected because it increases latency,
  cost, and another failure surface.
- Infer finality from phrases such as “final answer”: rejected because prose is
  not a stable protocol. Node boundaries and finish reasons are the authority.

## Consequences

- DeepSeek reasoning profiles no longer require a forced output-tool choice.
- The production failure mode caused by exhausted `final_answer` validation
  retries is removed.
- A no-tool ordinary text response is a valid final answer; the prompt must
  instruct the model not to expose planning or protocol prose.
- Candidate latency is bounded by model-node classification rather than raw
  output-tool argument deltas.
- ADR 0036 remains as historical rationale for the old design; current-state
  documentation follows this decision.
