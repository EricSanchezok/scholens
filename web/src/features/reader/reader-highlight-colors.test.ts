import { describe, expect, it } from "vitest";

import {
  readerHighlightColors,
  readerHighlightColorValue,
  readReaderHighlightColor,
} from "./reader-highlight-colors";

describe("Reader highlight colors", () => {
  it("exposes the complete document palette in stable order", () => {
    expect(readerHighlightColors).toEqual([
      "yellow",
      "red",
      "green",
      "blue",
      "purple",
      "magenta",
      "orange",
      "gray",
    ]);
  });

  it("falls back to blue for an unrecognized server value", () => {
    expect(readReaderHighlightColor("unknown")).toBe("blue");
    expect(readerHighlightColorValue("unknown")).toBe(
      "var(--color-document-highlight-blue)",
    );
  });
});
