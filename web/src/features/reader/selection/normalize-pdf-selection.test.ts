import { describe, expect, it } from "vitest";

import {
  buildPageTextGeometryIndex,
  type GeometryRect,
} from "./page-text-geometry";
import {
  clampDeadZoneEnd,
  columnStripItems,
  normalizeForComparison,
  normalizePdfSelection,
  verticalGapBetween,
} from "./normalize-pdf-selection";
import type { GeometryItem } from "./page-text-geometry";

function rectFor(left: number, top: number, width: number, height: number) {
  return { height, left, top, width };
}

function setClientRect(element: HTMLElement, rect: GeometryRect) {
  Object.defineProperty(element, "getBoundingClientRect", {
    configurable: true,
    value: () => rect,
  });
}

function makeTextLayer() {
  const layer = document.createElement("div");
  layer.className = "pdf-text-layer";
  document.body.append(layer);
  return layer;
}

function makeSpan(layer: HTMLElement, text: string, rect: GeometryRect) {
  const span = document.createElement("span");
  span.textContent = text;
  setClientRect(span, rect);
  layer.append(span);
  return span;
}

function buildRangeFromOffsets(layer: HTMLElement, start: number, end: number) {
  const spans = Array.from(layer.querySelectorAll<HTMLElement>("span")).filter(
    (span) => span.textContent?.trim(),
  );
  const startSpan = spans[0]!;
  const endSpan = spans[spans.length - 1]!;
  const range = document.createRange();
  range.setStart(
    startSpan.firstChild!,
    Math.min(start, startSpan.textContent!.length),
  );
  range.setEnd(endSpan.firstChild!, Math.min(end, endSpan.textContent!.length));
  return range;
}

describe("normalizeForComparison", () => {
  it("normalizes NFKC, whitespace, and hyphenated line breaks", () => {
    expect(normalizeForComparison("  Hello \n world  ")).toBe("Hello world");
    expect(normalizeForComparison("revolu-\ntion")).toBe("revolution");
    expect(normalizeForComparison("ｆｕｌｌ")).toBe("full");
  });
});

describe("verticalGapBetween", () => {
  const make = (left: number, top: number, width: number, height: number) =>
    ({
      centerX: left + width / 2,
      centerY: top + height / 2,
      domNode: document.createElement("span"),
      end: 0,
      rect: rectFor(left, top, width, height),
      start: 0,
      text: "",
    }) as GeometryItem;

  it("returns the gap between consecutive lines", () => {
    expect(verticalGapBetween(make(0, 0, 100, 20), make(0, 30, 100, 20))).toBe(
      10,
    );
  });

  it("returns 0 for overlapping or adjacent lines", () => {
    expect(verticalGapBetween(make(0, 0, 100, 20), make(0, 18, 100, 20))).toBe(
      0,
    );
  });
});

describe("columnStripItems", () => {
  const make = (left: number, top: number, width: number) =>
    ({
      centerX: left + width / 2,
      centerY: top,
      domNode: document.createElement("span"),
      end: 0,
      rect: rectFor(left, top, width, 10),
      start: 0,
      text: "",
    }) as GeometryItem;

  it("keeps items inside the anchor-head horizontal envelope", () => {
    const items = [make(0, 0, 100), make(400, 0, 100), make(800, 0, 100)];
    const kept = columnStripItems(items, 50, 450);
    expect(kept).toHaveLength(2);
  });
});

describe("clampDeadZoneEnd", () => {
  it("clamps the end when the pointer is in a large vertical gap", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "First paragraph", rectFor(0, 0, 200, 20));
    makeSpan(layer, "Second paragraph", rectFor(0, 200, 220, 20));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    // Pointer at y=100 sits between the two paragraphs (gap 180px).
    const clamped = clampDeadZoneEnd(index, 0, index.length, 100);
    expect(clamped).toBe(index.items[0]!.end);
  });

  it("keeps the end when the pointer is inside a line", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "First paragraph", rectFor(0, 0, 200, 20));
    makeSpan(layer, "Second paragraph", rectFor(0, 200, 220, 20));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    expect(clampDeadZoneEnd(index, 0, index.length, 210)).toBe(index.length);
  });
});

describe("normalizePdfSelection", () => {
  it("returns undefined for a range outside the text layer", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "Hello", rectFor(0, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const outside = document.createElement("div");
    document.body.append(outside);
    const range = document.createRange();
    range.selectNode(outside);
    expect(
      normalizePdfSelection({ index, range, previous: undefined }),
    ).toBeUndefined();
    outside.remove();
  });

  it("normalizes a range into text and rects", () => {
    const layer = makeTextLayer();
    const first = makeSpan(layer, "The NLP", rectFor(0, 0, 80, 20));
    makeSpan(layer, "landscape", rectFor(90, 0, 100, 20));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const range = document.createRange();
    range.setStart(first.firstChild!, 0);
    range.setEnd(first.firstChild!, 7);
    const result = normalizePdfSelection({ index, range, previous: undefined });
    expect(result?.text).toBe("The NLP");
    expect(result?.rects).toHaveLength(1);
    expect(result?.start).toBe(0);
    expect(result?.end).toBe(7);
  });

  it("falls back to the browser text when geometry and browser genuinely diverge", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "alpha", rectFor(0, 0, 50, 10));
    makeSpan(layer, "beta", rectFor(60, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const range = buildRangeFromOffsets(layer, 0, 9);
    // Force the browser text to a non-prefix corruption (font substitution
    // style divergence), so the honest fallback path is exercised.
    const originalToString = Range.prototype.toString;
    Range.prototype.toString = () => "alpha gamme";
    const result = normalizePdfSelection({ index, range, previous: undefined });
    Range.prototype.toString = originalToString;
    expect(result?.text).toBe("alpha gamme");
    expect(result?.rects).toHaveLength(2);
  });

  it("rejects empty selections", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "Hello", rectFor(0, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const range = buildRangeFromOffsets(layer, 0, 0);
    expect(
      normalizePdfSelection({ index, range, previous: undefined }),
    ).toBeUndefined();
  });

  it("applies the overshoot guard against a previous stable selection", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "short", rectFor(0, 0, 50, 10));
    makeSpan(
      layer,
      "This is a very long paragraph with many many words that extends far beyond eighty characters in total length",
      rectFor(0, 100, 600, 20),
    );
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const previous = {
      start: 0,
      end: 5,
      text: "short",
      rects: [rectFor(0, 0, 50, 10)],
    };
    const range = buildRangeFromOffsets(layer, 0, index.length);
    expect(normalizePdfSelection({ index, range, previous })).toBeUndefined();
  });

  it("allows a reasonable extension beyond the previous selection", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "The NLP landscape", rectFor(0, 0, 200, 20));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const previous = {
      start: 0,
      end: 7,
      text: "The NLP",
      rects: [rectFor(0, 0, 80, 20)],
    };
    const range = buildRangeFromOffsets(layer, 0, index.length);
    const result = normalizePdfSelection({ index, range, previous });
    expect(result?.text).toBe("The NLP landscape");
  });
});
