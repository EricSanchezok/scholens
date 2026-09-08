import { expect, test } from "@playwright/test";

test("serves the public telemetry URL from the production build", async ({
  request,
}) => {
  const response = await request.post("/__telemetry/web-performance", {
    data: {
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
    },
    headers: { "sec-fetch-site": "same-origin" },
  });

  expect(response.status()).toBe(204);
  expect(response.headers()["cache-control"]).toContain("no-store");
});
