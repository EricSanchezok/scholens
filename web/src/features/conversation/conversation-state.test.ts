import { describe, expect, it } from "vitest";

import {
  createLiveTurn,
  persistedResponseStatus,
  reduceLiveTurn,
  reduceLiveTurnEvents,
} from "./conversation-state";

const running = {
  kind: "activity" as const,
  id: "search-1",
  sequence: 2,
  category: "search" as const,
  state: "running" as const,
  subject: "reasoning compression",
};
const responseId = "60000000-0000-4000-8000-000000000001";
const turnId = "50000000-0000-4000-8000-000000000001";

function event<T extends object>(payload: T) {
  return { response_id: responseId, ...payload };
}

function readyEvent({
  suggestions = null,
  variantIndex = 1,
}: {
  suggestions?: string[] | null;
  variantIndex?: number;
} = {}) {
  return {
    type: "response_ready" as const,
    turn: {
      branch: { count: 1, index: 1 },
      depth: 1,
      id: turnId,
      user_query: "Question",
      locale: "en" as const,
      time_zone: "Asia/Shanghai",
      reasoning_level: "standard",
      paper_context: { kind: "library" as const },
      parent_turn_id: null,
      contexts: [],
      selected_response_id: responseId,
      suggestions,
      responses: [
        {
          id: responseId,
          variant_index: variantIndex,
          status: "completed" as const,
          content: "Canonical answer",
          references: null,
          artifacts: null,
          duration_ms: 18_400,
          trace: {
            entries: [{ ...running, state: "succeeded" as const }],
            citation_summary: {
              source_count: 3,
              annotation_count: 2,
              rejected_source_count: 0,
            },
          },
        },
      ],
    },
  };
}

describe("Home live conversation state", () => {
  it("reconciles a detached stream from the canonical persisted response", () => {
    const turn = readyEvent().turn;

    expect(persistedResponseStatus([turn], turnId, responseId)).toBe(
      "completed",
    );
    expect(
      persistedResponseStatus([turn], turnId, "missing-response"),
    ).toBeUndefined();
  });

  it("treats a server cancellation as terminal without fabricating a failure", () => {
    const turn = reduceLiveTurn(
      createLiveTurn(turnId, responseId, "Question"),
      event({ type: "cancelled", turn_id: turnId }),
    );

    expect(turn?.state).toBe("cancelled");
    expect(turn?.failure).toBeNull();
    expect(turn?.durationMs).toBeGreaterThanOrEqual(0);
  });

  it("classifies one provisional item as progress without duplicating text", () => {
    let turn = createLiveTurn("turn-1", responseId, "Compare the papers");
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_start",
        item_id: "assistant:turn-1:1",
        sequence: 1,
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:1",
        delta: "I’ll inspect the available research.",
      }),
    )!;
    expect(turn.provisionalItems[0]?.content).toBe(
      "I’ll inspect the available research.",
    );

    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_complete",
        item: {
          id: "assistant:turn-1:1",
          sequence: 1,
          phase: "progress",
          content: "I’ll inspect the available research.",
        },
      }),
    )!;

    expect(turn.provisionalItems).toEqual([]);
    expect(turn.content).toBe("");
    expect(turn.entries).toEqual([
      {
        kind: "progress",
        id: "assistant:turn-1:1",
        sequence: 1,
        content: "I’ll inspect the available research.",
      },
    ]);
  });

  it("keeps final text in the answer and ignores late deltas", () => {
    let turn = createLiveTurn("turn-1", responseId, "Question");
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_start",
        item_id: "assistant:turn-1:3",
        sequence: 3,
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:3",
        delta: "Final answer",
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_complete",
        item: {
          id: "assistant:turn-1:3",
          sequence: 3,
          phase: "final",
          content: "Final answer",
        },
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:3",
        delta: " duplicated",
      }),
    )!;

    expect(turn.content).toBe("Final answer");
    expect(turn.provisionalItems).toEqual([]);
  });

  it("updates activity by ID, preserves order, and rejects stale running state", () => {
    let turn = createLiveTurn("turn-1", responseId, "Compare the papers");
    turn = reduceLiveTurn(
      turn,
      event({ type: "activity", activity: running }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "activity",
        activity: {
          kind: "activity",
          id: "read-2",
          sequence: 3,
          category: "read",
          state: "running",
        },
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "activity",
        activity: { ...running, state: "failed" },
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({ type: "activity", activity: running }),
    )!;

    expect(
      turn.entries.map((entry) =>
        entry.kind === "activity" ? [entry.id, entry.state] : [entry.id],
      ),
    ).toEqual([
      ["search-1", "failed"],
      ["read-2", "running"],
    ]);
  });

  it("uses response_ready as canonical history before complete closes the stream", () => {
    let turn = reduceLiveTurn(
      createLiveTurn(turnId, responseId, "Question"),
      readyEvent(),
    );

    expect(turn?.state).toBe("ready");
    expect(turn?.content).toBe("Canonical answer");
    expect(turn?.entries[0]).toMatchObject({ state: "succeeded" });
    expect(turn?.trace?.citation_summary?.source_count).toBe(3);
    expect(turn?.readyTurn?.id).toBe(turnId);
    expect(turn?.durationMs).toBe(18_400);

    turn = reduceLiveTurn(turn, event({ type: "complete", turn_id: turnId }));
    expect(turn?.state).toBe("complete");

    turn = reduceLiveTurn(
      turn,
      event({
        type: "activity",
        activity: { ...running, state: "failed" },
      }),
    );
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:late",
        delta: "late text",
      }),
    );

    expect(turn?.entries[0]).toMatchObject({ state: "succeeded" });
    expect(turn?.provisionalItems).toEqual([]);
  });

  it("adds late suggestions only after the response is ready", () => {
    let turn = reduceLiveTurn(
      createLiveTurn(turnId, responseId, "Question"),
      readyEvent(),
    );
    turn = reduceLiveTurn(
      turn,
      event({
        type: "suggestions",
        turn_id: turnId,
        suggestions: ["One", "Two", "Three"],
      }),
    );

    expect(turn?.suggestions).toEqual(["One", "Two", "Three"]);
    expect(turn?.readyTurn?.suggestions).toEqual(["One", "Two", "Three"]);
  });

  it("ignores stale suggestions and a complete event before response_ready", () => {
    const streaming = createLiveTurn(turnId, responseId, "Question");
    const prematurelyCompleted = reduceLiveTurn(
      streaming,
      event({ type: "complete", turn_id: turnId }),
    );
    const ready = reduceLiveTurn(prematurelyCompleted, readyEvent());
    const stale = reduceLiveTurn(
      ready,
      event({
        type: "suggestions",
        turn_id: "50000000-0000-4000-8000-000000000099",
        suggestions: ["Stale one", "Stale two", "Stale three"],
      }),
    );

    expect(prematurelyCompleted?.state).toBe("streaming");
    expect(stale?.suggestions).toBeNull();
  });

  it("keeps a retried variant ready and ignores a later stream error", () => {
    let turn = reduceLiveTurn(
      createLiveTurn(turnId, responseId, "Question", "retry"),
      readyEvent({
        suggestions: ["One", "Two", "Three"],
        variantIndex: 2,
      }),
    );
    turn = reduceLiveTurn(
      turn,
      event({
        type: "error",
        error: { code: "late_sidecar_failure", retryable: false },
      }),
    );

    expect(turn?.state).toBe("ready");
    expect(turn?.variantIndex).toBe(2);
    expect(turn?.failure).toBeNull();
  });

  it("retains safe diagnostics from a terminal stream error", () => {
    const turn = reduceLiveTurn(
      createLiveTurn("turn-1", responseId, "Question"),
      event({
        type: "error",
        error: {
          code: "chat_stream_failed",
          kind: "dependency_failure",
          retryable: true,
          diagnostic_id: "diagnostic-123",
        },
      }),
    );

    expect(turn?.state).toBe("error");
    expect(turn?.failure).toEqual({
      code: "chat_stream_failed",
      kind: "dependency_failure",
      retryable: true,
      correlationId: undefined,
      diagnosticId: "diagnostic-123",
    });
  });

  it("ignores events emitted for a different response variant", () => {
    const turn = createLiveTurn("turn-1", responseId, "Question", "retry");
    const next = reduceLiveTurn(turn, {
      type: "assistant_item_delta",
      response_id: "60000000-0000-4000-8000-000000000099",
      item_id: "assistant:turn-1:late",
      delta: "stale variant",
    });

    expect(next).toEqual(turn);
  });

  it("reduces animation-frame delta batches in their original order", () => {
    const started = reduceLiveTurn(
      createLiveTurn("turn-1", responseId, "Question"),
      event({
        type: "assistant_item_start",
        item_id: "assistant:turn-1:1",
        sequence: 1,
      }),
    );
    const next = reduceLiveTurnEvents(started, [
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:1",
        delta: "流式",
      }),
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:1",
        delta: "内容",
      }),
    ]);

    expect(next?.provisionalItems[0]?.content).toBe("流式内容");
  });
});
