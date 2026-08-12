import { describe, expect, it } from "vitest";

import {
  updateLatestTurnSuggestions,
  upsertConversationTurn,
} from "./conversation-cache";

type ConversationTurn = NonNullable<
  Parameters<typeof upsertConversationTurn>[1]
>;

function fixtureTurn(id: string, sequence: number): ConversationTurn {
  return {
    contexts: [],
    id,
    locale: "en",
    reasoning_level: "standard",
    responses: [],
    scope: null,
    selected_response_id: null,
    sequence,
    suggestions: null,
    time_zone: "Asia/Shanghai",
    user_query: `Question ${sequence}`,
  };
}

describe("conversation turn cache", () => {
  it("upserts the response_ready snapshot without a refetch", () => {
    const first = fixtureTurn("50000000-0000-4000-8000-000000000001", 1);
    const readyTurn = fixtureTurn("50000000-0000-4000-8000-000000000002", 2);

    const next = upsertConversationTurn(
      { items: [first], next_cursor: null },
      readyTurn,
    );

    expect(next.items).toEqual([first, readyTurn]);
  });

  it("updates suggestions only while the event still targets the latest turn", () => {
    const first = fixtureTurn("50000000-0000-4000-8000-000000000001", 1);
    const latest = fixtureTurn("50000000-0000-4000-8000-000000000002", 2);
    const cache = { items: [first, latest], next_cursor: null };

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
