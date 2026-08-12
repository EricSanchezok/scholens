import { describe, expect, it } from "vitest";

import {
  normalizeReaderSelectionRects,
  selectReaderViewportPage,
} from "./pdf-page";

describe("normalizeReaderSelectionRects", () => {
  it("normalizes browser rectangles against the rendered PDF page", () => {
    expect(
      normalizeReaderSelectionRects(
        { left: 100, top: 200, width: 400, height: 800 },
        [{ left: 140, top: 280, width: 120, height: 40 }],
      ),
    ).toEqual([{ x: 0.1, y: 0.1, width: 0.3, height: 0.05 }]);
  });

  it("clips rectangles to normalized bounds and ignores empty rectangles", () => {
    expect(
      normalizeReaderSelectionRects(
        { left: 100, top: 200, width: 400, height: 800 },
        [
          { left: 0, top: 0, width: 600, height: 1200 },
          { left: 100, top: 200, width: 0, height: 20 },
        ],
      ),
    ).toEqual([{ x: 0, y: 0, width: 1, height: 1 }]);
  });

  it("does not create anchors for an unmeasurable page", () => {
    expect(
      normalizeReaderSelectionRects({ left: 0, top: 0, width: 0, height: 0 }, [
        { left: 0, top: 0, width: 10, height: 10 },
      ]),
    ).toEqual([]);
  });

  it("coalesces overlapping PDF text fragments on the same visual line", () => {
    expect(
      normalizeReaderSelectionRects(
        { left: 0, top: 0, width: 1000, height: 1000 },
        [
          { left: 100, top: 100, width: 300, height: 20 },
          { left: 105, top: 101, width: 290, height: 20 },
          { left: 405, top: 100, width: 100, height: 20 },
          { left: 100, top: 130, width: 250, height: 20 },
          { left: 700, top: 100, width: 100, height: 20 },
        ],
      ),
    ).toEqual([
      { x: 0.1, y: 0.1, width: 0.405, height: 0.021 },
      { x: 0.7, y: 0.1, width: 0.1, height: 0.02 },
      { x: 0.1, y: 0.13, width: 0.25, height: 0.02 },
    ]);
  });
});

describe("selectReaderViewportPage", () => {
  it("selects the page occupying the largest part of the viewport", () => {
    expect(
      selectReaderViewportPage({ top: 100, bottom: 900 }, [
        { pageNumber: 1, top: -500, bottom: 250 },
        { pageNumber: 2, top: 266, bottom: 1016 },
      ]),
    ).toBe(2);
  });

  it("uses proximity to the viewport center when pages are equally visible", () => {
    expect(
      selectReaderViewportPage({ top: 0, bottom: 800 }, [
        { pageNumber: 1, top: -200, bottom: 400 },
        { pageNumber: 2, top: 400, bottom: 900 },
      ]),
    ).toBe(2);
  });
});
