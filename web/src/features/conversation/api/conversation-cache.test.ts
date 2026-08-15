import { describe, expect, it } from "vitest";

import {
  updateLatestTurnSuggestions,
  upsertConversationTurn,
} from "./conversation-cache";

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
