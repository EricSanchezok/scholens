import { describe, expect, it } from "vitest";

import { pwaColors } from "@/design-system/generated/theme-metadata";
import manifest from "./manifest";

describe("Web App Manifest", () => {
  it("publishes installable raven assets without constraining orientation", () => {
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
    expect(value).not.toHaveProperty("orientation");
    expect(value.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ sizes: "192x192" }),
        expect.objectContaining({ sizes: "512x512" }),
        expect.objectContaining({ purpose: "maskable", sizes: "512x512" }),
        expect.objectContaining({ purpose: "monochrome", sizes: "512x512" }),
      ]),
    );
  });
});
