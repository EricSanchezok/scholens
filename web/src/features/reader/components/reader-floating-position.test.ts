import { describe, expect, it } from "vitest";

import { computeReaderFloatingPosition } from "./reader-floating-position";

const boundary = { bottom: 600, left: 0, right: 400, top: 0 };
const floating = { height: 120, width: 240 };

describe("computeReaderFloatingPosition", () => {
  it("places the surface above the selection when it fits", () => {
    expect(
      computeReaderFloatingPosition({
        anchor: { bottom: 340, left: 120, right: 280, top: 320 },
        boundary,
        floating,
      }),
    ).toMatchObject({ left: 80, placement: "top", top: 192 });
  });

  it("flips below a selection near the visible top edge", () => {
    expect(
      computeReaderFloatingPosition({
        anchor: { bottom: 44, left: 120, right: 280, top: 24 },
        boundary,
        floating,
      }),
    ).toMatchObject({ placement: "bottom", top: 52 });
  });

  it("shifts horizontally instead of crossing the visible boundary", () => {
    const leftEdge = computeReaderFloatingPosition({
      anchor: { bottom: 340, left: 0, right: 40, top: 320 },
      boundary,
      floating,
    });
    const rightEdge = computeReaderFloatingPosition({
      anchor: { bottom: 340, left: 360, right: 400, top: 320 },
      boundary,
      floating,
    });

    expect(leftEdge.left).toBe(8);
    expect(rightEdge.left).toBe(152);
  });

  it("limits an oversized surface to the available visible area", () => {
    expect(
      computeReaderFloatingPosition({
        anchor: { bottom: 310, left: 190, right: 210, top: 290 },
        boundary: { bottom: 260, left: 20, right: 220, top: 100 },
        floating: { height: 300, width: 300 },
      }),
    ).toEqual({
      left: 28,
      maxHeight: 144,
      maxWidth: 184,
      placement: "top",
      top: 108,
    });
  });
});
