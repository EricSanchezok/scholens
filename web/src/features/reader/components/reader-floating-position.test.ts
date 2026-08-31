import { describe, expect, it } from "vitest";

import { computeReaderFloatingPosition } from "./reader-floating-position";

const boundary = { bottom: 600, left: 0, right: 400, top: 0 };
const floating = { height: 120, width: 240 };

describe("computeReaderFloatingPosition", () => {
  it("places the surface below the selection when it fits", () => {
    expect(
      computeReaderFloatingPosition({
        anchor: { bottom: 340, left: 120, right: 280, top: 320 },
        boundary,
        floating,
      }),
    ).toMatchObject({ left: 80, placement: "bottom", top: 348 });
  });

  it("flips above a selection near the visible bottom edge", () => {
    expect(
      computeReaderFloatingPosition({
        anchor: { bottom: 576, left: 120, right: 280, top: 556 },
        boundary,
        floating,
      }),
    ).toMatchObject({ placement: "top", top: 428 });
  });

  it("keeps a locked placement stable as preview content grows", () => {
    const initial = computeReaderFloatingPosition({
      anchor: { bottom: 340, left: 120, right: 280, top: 320 },
      boundary,
      floating,
      lockedPlacement: "bottom",
    });
    const grownPreview = computeReaderFloatingPosition({
      anchor: { bottom: 340, left: 120, right: 280, top: 320 },
      boundary,
      floating,
      lockedPlacement: "bottom",
    });

    expect(grownPreview.placement).toBe(initial.placement);
    expect(grownPreview.top).toBe(initial.top);
    expect(grownPreview.contentMaxHeight).toBe(initial.contentMaxHeight);
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
    ).toMatchObject({
      left: 28,
      maxHeight: 144,
      maxWidth: 184,
      placement: "top",
      top: 108,
      visible: false,
    });
  });

  it("hides the surface when the selection leaves the visible boundary", () => {
    expect(
      computeReaderFloatingPosition({
        anchor: { bottom: -12, left: 120, right: 280, top: -32 },
        boundary,
        floating,
      }).visible,
    ).toBe(false);
  });
});
