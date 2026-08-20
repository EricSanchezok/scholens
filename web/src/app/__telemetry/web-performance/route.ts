import { NextResponse } from "next/server";

import { webPerformanceEventSchema } from "@/lib/observability/web-performance-contract";

const MAX_CONTENT_LENGTH = 4_096;

function noStore(status = 204) {
  return new NextResponse(null, {
    headers: { "cache-control": "private, no-store" },
    status,
  });
}

export async function POST(request: Request) {
  const fetchSite = request.headers.get("sec-fetch-site");
  if (fetchSite && fetchSite !== "same-origin") return noStore();
  const contentLength = Number(request.headers.get("content-length") ?? 0);
  if (contentLength > MAX_CONTENT_LENGTH) return noStore(413);

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return noStore(400);
  }
  const parsed = webPerformanceEventSchema.safeParse(body);
  if (!parsed.success) return noStore(400);

  const ray = request.headers.get("cf-ray") ?? "";
  const country = request.headers.get("cf-ipcountry")?.toUpperCase();
  console.info(
    JSON.stringify({
      ...parsed.data,
      cf_colo: ray.includes("-") ? ray.split("-").at(-1) : undefined,
      country_group: country === "CN" ? "CN" : "non-CN",
      event: "web_performance",
      received_at: new Date().toISOString(),
    }),
  );
  return noStore();
}
