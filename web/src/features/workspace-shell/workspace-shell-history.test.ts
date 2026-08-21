import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/schema";
import {
  flattenConversationPages,
  groupConversationHistory,
} from "./workspace-shell";

type Conversation = components["schemas"]["ConversationSummaryResponse"];

function conversation(
  id: string,
  updatedAt: string,
  pinnedAt: string | null = null,
): Conversation {
  return {
    archived_at: null,
    capabilities: {
      archive: true,
      delete: true,
      detach: false,
      move: true,
      pin: true,
      rename: true,
      send: true,
      share: false,
    },
    id,
    pinned_at: pinnedAt,
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: null,
    scope_label: null,
    scope_type: "global",
    title: id,
    updated_at: updatedAt,
  };
}

describe("workspace conversation history", () => {
  it("deduplicates conversations while preserving cross-page order", () => {
    const first = conversation(
      "10000000-0000-4000-8000-000000000001",
      "2026-08-21T10:00:00Z",
    );
    const second = conversation(
      "10000000-0000-4000-8000-000000000002",
      "2026-08-20T10:00:00Z",
    );

    expect(
      flattenConversationPages([
        { items: [first], next_cursor: "page-two" },
        { items: [first, second], next_cursor: null },
      ]).map((item) => item.id),
    ).toEqual([first.id, second.id]);
  });

  it("keeps date groups coherent when a group crosses page boundaries", () => {
    const groups = groupConversationHistory(
      [
        conversation(
          "10000000-0000-4000-8000-000000000001",
          "2026-08-21T10:00:00Z",
        ),
        conversation(
          "10000000-0000-4000-8000-000000000002",
          "2026-08-21T07:00:00Z",
        ),
        conversation(
          "10000000-0000-4000-8000-000000000003",
          "2026-08-18T10:00:00Z",
        ),
        conversation(
          "10000000-0000-4000-8000-000000000004",
          "2026-07-02T10:00:00Z",
        ),
      ],
      "en",
      {
        previous30Days: "Previous 30 days",
        previous7Days: "Previous 7 days",
        today: "Today",
        yesterday: "Yesterday",
      },
      new Date("2026-08-21T12:00:00Z"),
    );

    expect(groups.map((group) => [group.title, group.items.length])).toEqual([
      ["Today", 2],
      ["Previous 7 days", 1],
      ["July 2026", 1],
    ]);
  });
});
