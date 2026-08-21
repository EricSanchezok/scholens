import { describe, expect, it } from "vitest";

import { pwaColors } from "@/design-system/generated/theme-metadata";
import manifest from "./manifest";

describe("product identity manifest", () => {
  it("publishes standalone, adaptive, and monochrome launcher assets", () => {
    const value = manifest();

    expect(value).toMatchObject({
      background_color: pwaColors.light.canvas,
      display: "standalone",
      id: "/",
      name: "Scholens",
      scope: "/",
      short_name: "Scholens",
      start_url: "/",
      theme_color: pwaColors.light.canvas,
    });
    expect(value.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ purpose: "maskable", sizes: "512x512" }),
        expect.objectContaining({ purpose: "monochrome", sizes: "512x512" }),
      ]),
    );
  });
});
