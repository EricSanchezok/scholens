import { describe, expect, it } from "vitest";

import { formatActivityDuration } from "./format";

describe("formatActivityDuration", () => {
  it("uses localized English units", () => {
    expect(formatActivityDuration(5_000, "en")).toMatch(/5\s*sec/);
    expect(formatActivityDuration(30 * 60_000, "en")).toMatch(/30\s*min/);
    expect(formatActivityDuration(90 * 60_000, "en")).toMatch(/1\.5\s*hr/);
  });

  it("uses localized Simplified Chinese units", () => {
    expect(formatActivityDuration(5_000, "zh-CN")).toContain("秒");
    expect(formatActivityDuration(30 * 60_000, "zh-CN")).toContain("分钟");
    expect(formatActivityDuration(90 * 60_000, "zh-CN")).toContain("小时");
  });
});
