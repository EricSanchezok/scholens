import { NextResponse } from "next/server";

import {
  conversationPerformanceMetricNames,
  webTelemetryEventSchema,
} from "@/lib/observability/web-performance-contract";

const MAX_CONTENT_LENGTH = 4_096;
const CONVERSATION_METRICS = new Set<string>(
  conversationPerformanceMetricNames,
);
const READER_ANNOTATION_METRICS = new Set([
  "reader_annotation_anchor_resolve",
  "reader_annotation_mutation",
  "reader_annotation_preview",
  "pdf_render_restart",
]);

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
  const parsed = webTelemetryEventSchema.safeParse(body);
  if (!parsed.success) return noStore(400);

  const eventName = READER_ANNOTATION_METRICS.has(parsed.data.metric)
    ? "reader_annotation"
    : parsed.data.metric === "pdf_render_error"
      ? "pdf_render"
      : CONVERSATION_METRICS.has(parsed.data.metric)
        ? "conversation_performance"
        : "web_performance";

  const ray = request.headers.get("cf-ray") ?? "";
  const country = request.headers.get("cf-ipcountry")?.toUpperCase();
  console.info(
    JSON.stringify({
      ...parsed.data,
      cf_colo: ray.includes("-") ? ray.split("-").at(-1) : undefined,
      country_group: country === "CN" ? "CN" : "non-CN",
      event: eventName,
      received_at: new Date().toISOString(),
    }),
  );
  return noStore();
}
