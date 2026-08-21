import { describe, expect, it } from "vitest";

import {
  removeConversationSummary,
  updateConversationSummary,
  updateLatestTurnSuggestions,
  upsertConversationTurn,
} from "./conversation-cache";

type ConversationList = NonNullable<
  Parameters<typeof updateConversationSummary>[0]
>;

function fixtureConversation(id: string, title: string) {
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
    pinned_at: null,
    read_only: false,
    read_only_reason: null,
    scope_access: "active" as const,
    scope_id: null,
    scope_label: null,
    scope_type: "global" as const,
    title,
    updated_at: "2026-08-15T12:00:00Z",
  };
}

type ConversationTurn = NonNullable<
  Parameters<typeof upsertConversationTurn>[1]
>;

function fixtureTurn(
  id: string,
  depth: number,
  overrides: Partial<ConversationTurn> = {},
): ConversationTurn {
  return {
    branch: { count: 1, index: 1 },
    contexts: [],
    depth,
    id,
    locale: "en",
    paper_context: { kind: "library" },
    parent_turn_id: depth === 1 ? null : "parent-turn",
    reasoning_level: "standard",
    responses: [],
    selected_response_id: null,
    suggestions: null,
    time_zone: "Asia/Shanghai",
    user_query: `Question ${depth}`,
    ...overrides,
  };
}

describe("conversation turn cache", () => {
  it("upserts the response_ready snapshot without a refetch", () => {
    const first = fixtureTurn("50000000-0000-4000-8000-000000000001", 1);
    const readyTurn = fixtureTurn("50000000-0000-4000-8000-000000000002", 2);

    const next = upsertConversationTurn(
      { items: [first], next_cursor: null, path_revision: 4 },
      readyTurn,
    );

    expect(next.items).toEqual([first, readyTurn]);
    expect(next.path_revision).toBe(5);
  });

  it("replaces the abandoned suffix when an edited prompt becomes ready", () => {
    const root = fixtureTurn("50000000-0000-4000-8000-000000000001", 1);
    const oldPrompt = fixtureTurn("50000000-0000-4000-8000-000000000002", 2, {
      parent_turn_id: root.id,
    });
    const oldSuffix = fixtureTurn("50000000-0000-4000-8000-000000000003", 3, {
      parent_turn_id: oldPrompt.id,
    });
    const editedPrompt = fixtureTurn(
      "50000000-0000-4000-8000-000000000004",
      2,
      {
        branch: {
          count: 2,
          index: 2,
          previous_turn_id: oldPrompt.id,
        },
        parent_turn_id: root.id,
        user_query: "Edited question",
      },
    );

    const next = upsertConversationTurn(
      {
        items: [root, oldPrompt, oldSuffix],
        next_cursor: null,
        path_revision: 7,
      },
      editedPrompt,
    );

    expect(next.items).toEqual([root, editedPrompt]);
    expect(next.path_revision).toBe(8);
  });

  it("updates suggestions only while the event still targets the latest turn", () => {
    const first = fixtureTurn("50000000-0000-4000-8000-000000000001", 1);
    const latest = fixtureTurn("50000000-0000-4000-8000-000000000002", 2);
    const cache = {
      items: [first, latest],
      next_cursor: null,
      path_revision: 2,
    };

    expect(
      updateLatestTurnSuggestions(cache, latest.id, [
        "One",
        "Two",
        "Three",
      ])?.items.at(-1)?.suggestions,
    ).toEqual(["One", "Two", "Three"]);
    expect(
      updateLatestTurnSuggestions(cache, first.id, [
        "Stale one",
        "Stale two",
        "Stale three",
      ]),
    ).toBe(cache);
  });
});

describe("conversation list cache", () => {
  const first = fixtureConversation(
    "50000000-0000-4000-8000-000000000001",
    "First",
  );
  const second = fixtureConversation(
    "50000000-0000-4000-8000-000000000002",
    "Second",
  );
  const cache: ConversationList = {
    items: [first, second],
    next_cursor: "next-page",
  };

  it("updates a matching summary without changing pagination", () => {
    const next = updateConversationSummary(cache, first.id, {
      pinned_at: "2026-08-15T13:00:00Z",
      title: "Renamed",
    });

    expect(next?.items).toEqual([
      {
        ...first,
        pinned_at: "2026-08-15T13:00:00Z",
        title: "Renamed",
      },
      second,
    ]);
    expect(next?.next_cursor).toBe("next-page");
  });

  it("removes only the deleted summary", () => {
    const next = removeConversationSummary(cache, first.id);

    expect(next?.items).toEqual([second]);
    expect(next?.next_cursor).toBe("next-page");
  });

  it("updates and removes summaries across infinite pages", () => {
    const infinite = {
      pageParams: [undefined, "next-page"],
      pages: [
        { items: [first], next_cursor: "next-page" },
        { items: [second], next_cursor: null },
      ],
    };

    const updated = updateConversationSummary(infinite, second.id, {
      title: "Renamed on page two",
    });
    expect(updated?.pages[0]?.items[0]?.title).toBe("First");
    expect(updated?.pages[1]?.items[0]?.title).toBe("Renamed on page two");
    expect(updated?.pageParams).toEqual([undefined, "next-page"]);

    const removed = removeConversationSummary(updated, first.id);
    expect(removed?.pages[0]?.items).toEqual([]);
    expect(removed?.pages[1]?.items).toHaveLength(1);
  });
});
