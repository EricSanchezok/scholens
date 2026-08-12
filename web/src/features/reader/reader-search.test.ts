import { describe, expect, it } from "vitest";

import {
  flattenReaderSearchResults,
  moveReaderSearchCursor,
} from "./reader-search";

describe("reader search navigation", () => {
  it("flattens page counts into stable document-order matches", () => {
    expect(
      flattenReaderSearchResults([
        { count: 2, pageNumber: 2 },
        { count: 1, pageNumber: 5 },
      ]),
    ).toEqual([
      { ordinal: 1, pageNumber: 2 },
      { ordinal: 2, pageNumber: 2 },
      { ordinal: 3, pageNumber: 5 },
    ]);
  });

  it("wraps in either direction without inventing an empty match", () => {
    expect(moveReaderSearchCursor(2, 3, 1)).toBe(0);
    expect(moveReaderSearchCursor(0, 3, -1)).toBe(2);
    expect(moveReaderSearchCursor(0, 0, 1)).toBe(-1);
  });
});
