import { describe, expect, it } from "vitest";

import {
  findReaderPageSearchMatches,
  moveReaderSearchCursor,
} from "./reader-search";

describe("reader search navigation", () => {
  it("finds repeated matches inside one PDF text item", () => {
    const matches = findReaderPageSearchMatches({
      ordinalOffset: 0,
      pageNumber: 2,
      query: "agent",
      textItems: ["Agent systems let each agent collaborate."],
    });

    expect(matches).toMatchObject([
      {
        begin: { itemIndex: 0, offset: 0 },
        end: { itemIndex: 0, offset: 5 },
        id: "2:0",
        ordinal: 0,
        pageMatchIndex: 0,
      },
      {
        begin: { itemIndex: 0, offset: 23 },
        end: { itemIndex: 0, offset: 28 },
        id: "2:1",
        ordinal: 1,
        pageMatchIndex: 1,
      },
    ]);
  });

  it("maps one logical match across adjacent PDF text items", () => {
    expect(
      findReaderPageSearchMatches({
        ordinalOffset: 4,
        pageNumber: 3,
        query: "Open Agentic Web",
        textItems: ["The ", "Open", "Agentic", "Web", " is shared."],
      }),
    ).toMatchObject([
      {
        begin: { itemIndex: 1, offset: 0 },
        end: { itemIndex: 3, offset: 3 },
        ordinal: 4,
        pageNumber: 3,
      },
    ]);
  });

  it("matches without case sensitivity and ignores an empty query", () => {
    expect(
      findReaderPageSearchMatches({
        ordinalOffset: 0,
        pageNumber: 1,
        query: "SYNERGY",
        textItems: ["Synergy"],
      }),
    ).toHaveLength(1);
    expect(
      findReaderPageSearchMatches({
        ordinalOffset: 0,
        pageNumber: 1,
        query: "   ",
        textItems: ["Synergy"],
      }),
    ).toEqual([]);
  });

  it("wraps in either direction without inventing an empty match", () => {
    expect(moveReaderSearchCursor(2, 3, 1)).toBe(0);
    expect(moveReaderSearchCursor(0, 3, -1)).toBe(2);
    expect(moveReaderSearchCursor(0, 0, 1)).toBe(-1);
  });
});
