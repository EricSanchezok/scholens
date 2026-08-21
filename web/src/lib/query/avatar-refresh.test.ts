import { describe, expect, it } from "vitest";

import { nextAvatarRefreshInterval } from "./avatar-refresh";

const NOW = Date.parse("2026-08-21T10:00:00Z");

describe("nextAvatarRefreshInterval", () => {
  it("polls missing avatars within fifteen minutes", () => {
    expect(nextAvatarRefreshInterval([], NOW)).toBe(15 * 60 * 1_000);
    expect(nextAvatarRefreshInterval([null], NOW)).toBe(15 * 60 * 1_000);
  });

  it("refreshes one minute before the earliest signed URL expires", () => {
    expect(
      nextAvatarRefreshInterval(
        [
          { expires_at: "2026-08-21T10:15:00Z" },
          { expires_at: "2026-08-21T10:09:00Z" },
        ],
        NOW,
      ),
    ).toBe(8 * 60 * 1_000);
  });

  it("uses a thirty-second floor for expired or nearly expired URLs", () => {
    expect(
      nextAvatarRefreshInterval([{ expires_at: "2026-08-21T10:00:20Z" }], NOW),
    ).toBe(30 * 1_000);
  });
});
