import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildPageTextGeometryIndex,
  hitTestNearest,
  mapDomBoundaryToOffset,
  rectsForOffsets,
  sliceText,
  type GeometryRect,
} from "./page-text-geometry";

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

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("buildPageTextGeometryIndex", () => {
  it("indexes selectable spans with page-order offsets", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "Hello", rectFor(0, 0, 50, 10));
    makeSpan(layer, "world", rectFor(60, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 2, 1);

    expect(index.pageNumber).toBe(2);
    expect(index.version).toBe(1);
    expect(index.length).toBe(10);
    expect(index.items.map((item) => item.text)).toEqual(["Hello", "world"]);
    expect(index.items[0]!.start).toBe(0);
    expect(index.items[0]!.end).toBe(5);
    expect(index.items[1]!.start).toBe(5);
    expect(index.items[1]!.end).toBe(10);
  });

  it("skips endOfContent, image-role, and empty spans", () => {
    const layer = makeTextLayer();
    const sentinel = document.createElement("div");
    sentinel.className = "endOfContent";
    layer.append(sentinel);
    const image = document.createElement("span");
    image.setAttribute("role", "img");
    image.textContent = "x";
    setClientRect(image, rectFor(0, 0, 5, 5));
    layer.append(image);
    const empty = document.createElement("span");
    setClientRect(empty, rectFor(0, 0, 5, 5));
    layer.append(empty);
    makeSpan(layer, "Real", rectFor(0, 10, 40, 10));

    const index = buildPageTextGeometryIndex(layer, 1, 1);
    expect(index.items).toHaveLength(1);
    expect(index.items[0]!.text).toBe("Real");
  });

  it("skips nested search-highlight spans so each item is unique", () => {
    const layer = makeTextLayer();
    const outer = document.createElement("span");
    setClientRect(outer, rectFor(0, 0, 90, 10));
    const highlight = document.createElement("span");
    highlight.className = "pdf-search-match";
    highlight.textContent = "land";
    outer.append(highlight);
    outer.append("scape");
    layer.append(outer);

    const index = buildPageTextGeometryIndex(layer, 1, 1);
    expect(index.items).toHaveLength(1);
    expect(index.items[0]!.text).toBe("landscape");
  });

  it("skips spans with zero-size rectangles", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "Visible", rectFor(0, 0, 50, 10));
    makeSpan(layer, "Hidden", rectFor(0, 0, 0, 0));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    expect(index.items).toHaveLength(1);
  });
});

describe("hitTestNearest", () => {
  it("returns the item whose rectangle contains the point", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "left", rectFor(0, 0, 50, 10));
    makeSpan(layer, "right", rectFor(200, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);

    expect(hitTestNearest(index, { x: 220, y: 5 })?.text).toBe("right");
    expect(hitTestNearest(index, { x: 25, y: 5 })?.text).toBe("left");
  });

  it("returns the closest item for a point in whitespace", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "left", rectFor(0, 0, 50, 10));
    makeSpan(layer, "right", rectFor(200, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);

    expect(hitTestNearest(index, { x: 130, y: 5 })?.text).toBe("right");
  });

  it("returns undefined for an empty index", () => {
    const index = buildPageTextGeometryIndex(makeTextLayer(), 1, 1);
    expect(hitTestNearest(index, { x: 0, y: 0 })).toBeUndefined();
  });
});

describe("mapDomBoundaryToOffset", () => {
  it("maps a text-node boundary to its character offset", () => {
    const layer = makeTextLayer();
    const span = makeSpan(layer, "Hello", rectFor(0, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const node = span.firstChild!;
    expect(mapDomBoundaryToOffset(index, node, 0, true)).toBe(0);
    expect(mapDomBoundaryToOffset(index, node, 3, false)).toBe(3);
    expect(mapDomBoundaryToOffset(index, node, 5, false)).toBe(5);
  });

  it("clamps out-of-range text offsets", () => {
    const layer = makeTextLayer();
    const span = makeSpan(layer, "Hi", rectFor(0, 0, 20, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    const node = span.firstChild!;
    expect(mapDomBoundaryToOffset(index, node, 99, false)).toBe(2);
    expect(mapDomBoundaryToOffset(index, node, -1, true)).toBe(0);
  });

  it("resolves element boundaries proportionally across child nodes", () => {
    const layer = makeTextLayer();
    const outer = document.createElement("span");
    setClientRect(outer, rectFor(0, 0, 90, 10));
    const highlight = document.createElement("span");
    highlight.className = "pdf-search-match";
    highlight.textContent = "land";
    outer.append(highlight);
    outer.append("scape");
    layer.append(outer);
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    // Element boundary at child index 1 of 2 → roughly half the text.
    expect(
      mapDomBoundaryToOffset(index, outer, 1, false),
    ).toBeGreaterThanOrEqual(4);
    expect(mapDomBoundaryToOffset(index, outer, 1, false)).toBeLessThanOrEqual(
      5,
    );
  });

  it("falls back to nearest glyph for a container boundary", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "first", rectFor(0, 0, 50, 10));
    makeSpan(layer, "second", rectFor(0, 50, 60, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    // Layer element boundary with no rect maps to the start boundary (start=0).
    expect(mapDomBoundaryToOffset(index, layer, 0, false)).toBe(11);
  });
});

describe("sliceText and rectsForOffsets", () => {
  it("builds text with single spaces and rects per item", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "Hello", rectFor(0, 0, 50, 10));
    makeSpan(layer, "world", rectFor(60, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);

    expect(sliceText(index, 0, 5)).toBe("Hello");
    expect(sliceText(index, 0, 10)).toBe("Hello world");
    expect(sliceText(index, 6, 10)).toBe("orld");
    expect(rectsForOffsets(index, 0, 10)).toHaveLength(2);
    expect(rectsForOffsets(index, 0, 5)).toHaveLength(1);
  });

  it("trims whitespace-only ranges and returns empty for no items", () => {
    const layer = makeTextLayer();
    makeSpan(layer, "Hello", rectFor(0, 0, 50, 10));
    const index = buildPageTextGeometryIndex(layer, 1, 1);
    expect(sliceText(index, 5, 5)).toBe("");
    expect(rectsForOffsets(index, 5, 5)).toEqual([]);
  });
});
