import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/projects/one" }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
}));

import {
  beginRouteNavigation,
  performanceRouteGroup,
  reportCommittedRoute,
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
      const body = String(request?.body);
      if (JSON.parse(body).metric === "primary_content") bodies.push(body);
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: false })),
    );
    vi.spyOn(performance, "now").mockReturnValue(250);

    beginRouteNavigation("/projects/one");
    reportCommittedRoute("/projects/one");
    const { rerender } = renderHook(
      ({ ready }: { ready: boolean }) => usePrimaryContentReady(ready),
      { initialProps: { ready: true } },
    );
    await waitFor(() => expect(bodies).toHaveLength(1));

    rerender({ ready: true });
    expect(bodies).toHaveLength(1);

    navigation.pathname = "/projects/two";
    beginRouteNavigation("/projects/two");
    reportCommittedRoute("/projects/two");
    rerender({ ready: true });
    await waitFor(() => expect(bodies).toHaveLength(2));

    const events = bodies.map(
      (body) => JSON.parse(body) as { to_route: string },
    );
    expect(events.map((event) => event.to_route)).toEqual([
      "project-detail",
      "project-detail",
    ]);
  });

  it("never reuses a different destination's clock or browser uptime", () => {
    const bodies: { metric: string; value: number }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_input, request) => {
        bodies.push(JSON.parse(request.body));
        return Promise.resolve(new Response(null, { status: 204 }));
      }),
    );
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: false })),
    );
    vi.spyOn(performance, "now").mockReturnValue(206_000);
    beginRouteNavigation("/reader/first");
    reportCommittedRoute("/reader/second");
    navigation.pathname = "/reader/second";
    const { rerender } = renderHook(() => usePrimaryContentReady(true));
    expect(bodies).toHaveLength(0);
    vi.mocked(performance.now).mockReturnValue(206_020);
    reportCommittedRoute("/reader/first");
    navigation.pathname = "/reader/first";
    rerender();
    expect(bodies).toEqual([
      expect.objectContaining({ metric: "route_commit", value: 20 }),
      expect.objectContaining({ metric: "primary_content", value: 20 }),
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

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(JSON.parse(bodies[0]!)).toMatchObject({
      decoder: "jbig2",
      error_kind: "asset_unavailable",
      metric: "pdf_render_error",
      surface: "document",
      to_route: "reader",
    });
  });
});
