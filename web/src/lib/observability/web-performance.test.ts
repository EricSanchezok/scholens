import { describe, expect, it } from "vitest";

import { performanceRouteGroup } from "./web-performance";

describe("performanceRouteGroup", () => {
  it("removes identifiers and query state from telemetry dimensions", () => {
    expect(performanceRouteGroup("/")).toBe("home");
    expect(performanceRouteGroup("/library")).toBe("library");
    expect(
      performanceRouteGroup("/projects/50000000-0000-4000-8000-000000000001"),
    ).toBe("project-detail");
    expect(
      performanceRouteGroup("/reader/90000000-0000-4000-8000-000000000001"),
    ).toBe("reader");
    expect(performanceRouteGroup("/not-a-product-route")).toBe("unknown");
  });
});
