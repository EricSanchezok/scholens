import { describe, expect, it } from "vitest";

import type { ConversationTraceEntry } from "../conversation-state";
import { groupWorklogEntries } from "./conversation-worklog";

function activity(
  id: string,
  sequence: number,
  category: "search" | "read",
  state: "running" | "succeeded" | "failed" = "succeeded",
): ConversationTraceEntry {
  return {
    kind: "activity",
    id,
    sequence,
    category,
    state,
  };
}

describe("conversation worklog rows", () => {
  it("keeps consecutive tool activities as distinct rows", () => {
    const rows = groupWorklogEntries([
      activity("search-1", 1, "search"),
      activity("read-2", 2, "read"),
    ]);

    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.kind)).toEqual(["batch", "batch"]);
    expect(rows.map((row) => row.id)).toEqual([
      "activity:search-1",
      "activity:read-2",
    ]);
  });

  it("keeps progress entries in sequence order", () => {
    const entries: ConversationTraceEntry[] = [
      activity("read-3", 3, "read"),
      activity("search-1", 1, "search"),
      {
        kind: "progress",
        id: "assistant-2",
        sequence: 2,
        content: "The first strategy was too narrow, so I’ll broaden it.",
      },
    ];

    expect(groupWorklogEntries(entries).map((row) => row.kind)).toEqual([
      "batch",
      "progress",
      "batch",
    ]);
  });

  it("keeps successful and failed activities in separate batches", () => {
    const rows = groupWorklogEntries([
      activity("search-failed", 1, "search", "failed"),
      activity("read-succeeded", 2, "read", "succeeded"),
    ]);

    expect(rows).toHaveLength(2);
    expect(rows).toMatchObject([
      { kind: "batch", state: "failed" },
      { kind: "batch", state: "succeeded" },
    ]);
  });
});
