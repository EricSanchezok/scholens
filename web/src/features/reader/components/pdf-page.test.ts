import { describe, expect, it } from "vitest";

import { normalizeReaderSelectionRects } from "./pdf-page";

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
});
