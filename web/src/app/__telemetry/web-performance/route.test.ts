import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

const validEvent = {
  device_class: "mobile",
  effective_type: "4g",
  event_id: "f4cfddaa-1438-4b29-8f05-e926359cbc2a",
  from_route: "library",
  metric: "route_commit",
  navigation_kind: "soft",
  release: "development",
  save_data: false,
  to_route: "projects",
  value: 428,
};

function request(body: unknown, headers: Record<string, string> = {}) {
  return new Request("http://localhost/__telemetry/web-performance", {
    body: JSON.stringify(body),
    headers: { "content-type": "application/json", ...headers },
    method: "POST",
  });
}

describe("web performance telemetry route", () => {
  afterEach(() => vi.restoreAllMocks());

  it("logs only validated, low-cardinality fields", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const response = await POST(
      request(validEvent, {
        "cf-ipcountry": "CN",
        "cf-ray": "abc123-LAX",
        "sec-fetch-site": "same-origin",
      }),
    );

    expect(response.status).toBe(204);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(info).toHaveBeenCalledOnce();
    const logged = JSON.parse(info.mock.calls[0]![0] as string) as Record<
      string,
      unknown
    >;
    expect(logged).toMatchObject({
      cf_colo: "LAX",
      country_group: "CN",
      event: "web_performance",
      metric: "route_commit",
      value: 428,
    });
    expect(logged).not.toHaveProperty("ip");
    expect(logged).not.toHaveProperty("url");
    expect(logged).not.toHaveProperty("user_id");
  });

  it("rejects unknown fields and ignores cross-site submissions", async () => {
    expect(
      await POST(request({ ...validEvent, title: "private" })),
    ).toMatchObject({ status: 400 });
    expect(
      await POST(request(validEvent, { "sec-fetch-site": "cross-site" })),
    ).toMatchObject({ status: 204 });
  });

  it("accepts a content-free conversation milestone", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const response = await POST(
      request({
        device_class: "desktop",
        effective_type: "4g",
        event_id: "2b5724e5-b36d-4bfa-9b7e-e1f0b3092eb2",
        metric: "conversation_first_content",
        release: "development",
        save_data: false,
        stream_kind: "direct",
        to_route: "reader",
        value: 612,
      }),
    );

    expect(response.status).toBe(204);
    const logged = JSON.parse(info.mock.calls[0]![0] as string) as Record<
      string,
      unknown
    >;
    expect(logged).toMatchObject({
      event: "conversation_performance",
      metric: "conversation_first_content",
      stream_kind: "direct",
      to_route: "reader",
      value: 612,
    });
    expect(logged).not.toHaveProperty("conversation_id");
    expect(logged).not.toHaveProperty("content");
  });
});
