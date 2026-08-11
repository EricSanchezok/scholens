import { describe, expect, it } from "vitest";

import { homeTurns } from "./fixtures";
import {
  updateLatestTurnSuggestions,
  upsertConversationTurn,
} from "./conversation-cache";

describe("conversation turn cache", () => {
  it("upserts the response_ready snapshot without a refetch", () => {
    const readyTurn = {
      ...homeTurns[0]!,
      id: "50000000-0000-4000-8000-000000000002",
      sequence: 2,
    };

    const next = upsertConversationTurn(
      { items: [homeTurns[0]!], next_cursor: null },
      readyTurn,
    );

    expect(next.items).toEqual([homeTurns[0], readyTurn]);
  });

  it("updates suggestions only while the event still targets the latest turn", () => {
    const latest = {
      ...homeTurns[0]!,
      id: "50000000-0000-4000-8000-000000000002",
      sequence: 2,
      suggestions: null,
    };
    const cache = { items: [homeTurns[0]!, latest], next_cursor: null };

    expect(
      updateLatestTurnSuggestions(cache, latest.id, [
        "One",
        "Two",
        "Three",
      ])?.items.at(-1)?.suggestions,
    ).toEqual(["One", "Two", "Three"]);
    expect(
      updateLatestTurnSuggestions(cache, homeTurns[0]!.id, [
        "Stale one",
        "Stale two",
        "Stale three",
      ]),
    ).toBe(cache);
  });
});
