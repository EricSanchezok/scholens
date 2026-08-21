import { describe, expect, it } from "vitest";

import manifest from "./manifest";

describe("product identity manifest", () => {
  it("publishes standalone, adaptive, and monochrome launcher assets", () => {
    const value = manifest();

    expect(value).toMatchObject({
      display: "standalone",
      id: "/",
      name: "Scholens",
      scope: "/",
      short_name: "Scholens",
      start_url: "/",
    });
    expect(value.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ purpose: "maskable", sizes: "512x512" }),
        expect.objectContaining({ purpose: "monochrome", sizes: "512x512" }),
      ]),
    );
  });
});
