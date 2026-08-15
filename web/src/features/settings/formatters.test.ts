import { describe, expect, it } from "vitest";

import {
  addDaysToDateOnly,
  formatDateOnly,
  formatStorageKilobytes,
} from "./formatters";

describe("Settings formatters", () => {
  it("keeps date-only values on their calendar day in a UTC-negative zone", () => {
    const format = (
      value: Date | number,
      options?: Intl.DateTimeFormatOptions,
    ) =>
      new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Los_Angeles",
        ...options,
      }).format(value);

    expect(formatDateOnly("2026-08-10", format)).toBe("Aug 10, 2026");
    expect(formatDateOnly("2026-08-16", format)).toBe("Aug 16, 2026");
  });

  it("rejects impossible or timestamp-shaped date-only values", () => {
    const format = (value: Date | number) => String(value);
    expect(() => formatDateOnly("2026-02-30", format)).toThrow(
      "Invalid date-only value",
    );
    expect(() => formatDateOnly("2026-08-10T00:00:00Z", format)).toThrow(
      "Invalid date-only value",
    );
  });

  it("advances a date-only reset boundary across month and year ends", () => {
    expect(addDaysToDateOnly("2026-08-31", 1)).toBe("2026-09-01");
    expect(addDaysToDateOnly("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("formats the API KiB contract as binary human-readable storage", () => {
    const english = (value: number, options?: Intl.NumberFormatOptions) =>
      new Intl.NumberFormat("en-US", options).format(value);
    const chinese = (value: number, options?: Intl.NumberFormatOptions) =>
      new Intl.NumberFormat("zh-CN", options).format(value);

    expect(formatStorageKilobytes(200 * 1024, english)).toBe("200 MiB");
    expect(formatStorageKilobytes(3 * 1024 * 1024, english)).toBe("3 GiB");
    expect(formatStorageKilobytes(768 * 1024, chinese)).toBe("768 MiB");
  });
});
