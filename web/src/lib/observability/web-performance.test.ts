import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/projects/one" }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
}));

import {
  performanceRouteGroup,
  reportPdfRenderError,
  usePrimaryContentReady,
} from "./web-performance";

afterEach(() => {
  navigation.pathname = "/projects/one";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

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

  it("reports primary content again when a reused route changes identity", async () => {
    const bodies: string[] = [];
    const fetch = vi.fn((_input: RequestInfo | URL, request?: RequestInit) => {
      bodies.push(String(request?.body));
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: false })),
    );
    vi.spyOn(performance, "now").mockReturnValue(250);

    const { rerender } = renderHook(
      ({ ready }: { ready: boolean }) => usePrimaryContentReady(ready),
      { initialProps: { ready: true } },
    );
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    rerender({ ready: true });
    expect(fetch).toHaveBeenCalledTimes(1);

    navigation.pathname = "/projects/two";
    rerender({ ready: true });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));

    const events = bodies.map(
      (body) => JSON.parse(body) as { to_route: string },
    );
    expect(events.map((event) => event.to_route)).toEqual([
      "project-detail",
      "project-detail",
    ]);
  });

  it("reports a low-cardinality PDF render error", async () => {
    const bodies: string[] = [];
    const fetch = vi.fn((_input: RequestInfo | URL, request?: RequestInit) => {
      bodies.push(String(request?.body));
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: false })),
    );

    reportPdfRenderError({
      decoder: "jbig2",
      error_kind: "asset_unavailable",
      surface: "document",
    });

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(JSON.parse(bodies[0]!)).toMatchObject({
      decoder: "jbig2",
      error_kind: "asset_unavailable",
      metric: "pdf_render_error",
      surface: "document",
      to_route: "reader",
    });
  });
});
