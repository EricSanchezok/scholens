import { describe, expect, it } from "vitest";

import { GET } from "./route";

describe("service worker route", () => {
  it("serves a root-scoped, non-caching worker", async () => {
    const response = GET();
    const source = await response.text();
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain(
      "application/javascript",
    );
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(response.headers.get("service-worker-allowed")).toBe("/");
    expect(source).toContain('event.request.mode !== "navigate"');
    expect(source).not.toContain("caches.open");
    expect(source).not.toContain("Cache API");
  });

  it("contains a bilingual fallback without user research data", async () => {
    const source = await GET().text();
    expect(source).toContain("You’re offline");
    expect(source).toContain("当前处于离线状态");
    expect(source).toContain("does not store papers or account data");
  });
});
