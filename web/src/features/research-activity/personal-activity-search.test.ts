import { describe, expect, it } from "vitest";

import {
  parsePersonalActivityRange,
  serializePersonalActivityRange,
} from "./personal-activity-search";

describe("personal research activity URL state", () => {
  it("uses an omitted 365-day default", () => {
    expect(parsePersonalActivityRange(new URLSearchParams())).toBe("365d");
    expect(serializePersonalActivityRange("365d").toString()).toBe("");
  });

  it("round-trips supported ranges and normalizes invalid values", () => {
    for (const range of ["30d", "90d", "all"] as const) {
      expect(
        parsePersonalActivityRange(serializePersonalActivityRange(range)),
      ).toBe(range);
    }
    expect(parsePersonalActivityRange(new URLSearchParams("range=7d"))).toBe(
      "365d",
    );
  });
});
