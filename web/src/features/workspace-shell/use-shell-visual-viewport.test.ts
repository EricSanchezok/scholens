import { describe, expect, it } from "vitest";

import { readShellVisualViewport } from "./use-shell-visual-viewport";

describe("readShellVisualViewport", () => {
  it("uses the visual viewport metrics when available", () => {
    expect(
      readShellVisualViewport({ height: 640, offsetTop: 24 }, 844),
    ).toEqual({ height: 640, offsetTop: 24 });
  });

  it("falls back to the layout viewport height", () => {
    expect(readShellVisualViewport(null, 812)).toEqual({
      height: 812,
      offsetTop: 0,
    });
  });
});
