import { describe, expect, it } from "vitest";

import { isSearchQuery, normalizeSearchQuery } from "./query";

describe("search query policy", () => {
  it("normalizes surrounding whitespace", () => {
    expect(normalizeSearchQuery("  retrieval  ")).toBe("retrieval");
  });

  it("measures the minimum length in Unicode code points", () => {
    expect(isSearchQuery("a")).toBe(false);
    expect(isSearchQuery("检索")).toBe(true);
    expect(isSearchQuery("😀")).toBe(false);
    expect(isSearchQuery("😀😀")).toBe(true);
  });
});
