import { describe, expect, it } from "vitest";

import {
  parsePositiveInteger,
  readReaderPanel,
  readSourcePage,
} from "./reader-routing";

describe("reader URL state", () => {
  it("accepts only positive integer page numbers", () => {
    expect(parsePositiveInteger("12")).toBe(12);
    expect(parsePositiveInteger("0", 3)).toBe(3);
    expect(parsePositiveInteger("1.5", 3)).toBe(3);
    expect(parsePositiveInteger(null, 3)).toBe(3);
  });

  it("rejects unknown panel values", () => {
    expect(readReaderPanel("annotations")).toBe("annotations");
    expect(readReaderPanel("search")).toBeUndefined();
    expect(readReaderPanel("outline")).toBeUndefined();
    expect(readReaderPanel("translation")).toBeUndefined();
    expect(readReaderPanel(null)).toBeUndefined();
  });

  it("reads document source pages without trusting invalid locators", () => {
    expect(readSourcePage({ page_number: 8 })).toBe(8);
    expect(readSourcePage({ page: "4" })).toBe(4);
    expect(readSourcePage({ page_number: -1 })).toBeUndefined();
    expect(readSourcePage({ page: "chapter-two" })).toBeUndefined();
  });
});
