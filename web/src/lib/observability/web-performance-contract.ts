import { z } from "zod";

export const webPerformanceMetricNames = [
  "CLS",
  "FCP",
  "INP",
  "LCP",
  "TTFB",
  "primary_content",
  "route_commit",
  "route_feedback",
  "reader_annotation_anchor_resolve",
  "reader_annotation_mutation",
  "reader_annotation_preview",
  "pdf_render_restart",
] as const;

export const conversationPerformanceMetricNames = [
  "conversation_feedback",
  "conversation_accepted",
  "conversation_first_event",
  "conversation_first_content",
  "conversation_ready",
  "conversation_max_stall",
] as const;

export const pdfRenderErrorKinds = [
  "asset_unavailable",
  "document_open",
  "page_render",
] as const;

export const pdfRenderErrorDecoders = [
  "jbig2",
  "openjpeg",
  "qcms",
  "unknown",
] as const;

export const webPerformanceRouteGroups = [
  "documentation",
  "home",
  "library",
  "login",
  "project-detail",
  "projects",
  "reader",
  "unknown",
] as const;

export const webPerformanceEventSchema = z
  .object({
    device_class: z.enum(["desktop", "mobile"]),
    effective_type: z.enum(["slow-2g", "2g", "3g", "4g", "unknown"]).optional(),
    event_id: z.uuid(),
    from_route: z.enum(webPerformanceRouteGroups).optional(),
    metric: z.enum(webPerformanceMetricNames),
    navigation_kind: z.enum(["hard", "soft"]),
    rating: z.enum(["good", "needs-improvement", "poor"]).optional(),
    release: z.string().trim().min(1).max(64),
    save_data: z.boolean().optional(),
    to_route: z.enum(webPerformanceRouteGroups),
    value: z.number().finite().min(0).max(3_600_000),
  })
  .strict();

export const conversationPerformanceEventSchema = z
  .object({
    device_class: z.enum(["desktop", "mobile"]),
    effective_type: z.enum(["slow-2g", "2g", "3g", "4g", "unknown"]).optional(),
    event_id: z.uuid(),
    metric: z.enum(conversationPerformanceMetricNames),
    release: z.string().trim().min(1).max(64),
    save_data: z.boolean().optional(),
    stream_kind: z.enum(["direct", "resume"]).optional(),
    to_route: z.enum(webPerformanceRouteGroups),
    value: z.number().finite().min(0).max(3_600_000),
  })
  .strict();

export const pdfRenderErrorEventSchema = z
  .object({
    decoder: z.enum(pdfRenderErrorDecoders).optional(),
    device_class: z.enum(["desktop", "mobile"]),
    effective_type: z.enum(["slow-2g", "2g", "3g", "4g", "unknown"]).optional(),
    error_kind: z.enum(pdfRenderErrorKinds),
    event_id: z.uuid(),
    metric: z.literal("pdf_render_error"),
    release: z.string().trim().min(1).max(64),
    save_data: z.boolean().optional(),
    surface: z.enum(["document", "page"]),
    to_route: z.literal("reader"),
  })
  .strict();

export const webTelemetryEventSchema = z.union([
  webPerformanceEventSchema,
  conversationPerformanceEventSchema,
  pdfRenderErrorEventSchema,
]);

export type WebPerformanceEvent = z.infer<typeof webPerformanceEventSchema>;
export type ConversationPerformanceEvent = z.infer<
  typeof conversationPerformanceEventSchema
>;
export type PdfRenderErrorEvent = z.infer<typeof pdfRenderErrorEventSchema>;
export type ConversationPerformanceMetricName =
  (typeof conversationPerformanceMetricNames)[number];
export type ReaderAnnotationMetricName = Extract<
  WebPerformanceMetricName,
  | "reader_annotation_anchor_resolve"
  | "reader_annotation_mutation"
  | "reader_annotation_preview"
  | "pdf_render_restart"
>;
export type WebTelemetryEvent = z.infer<typeof webTelemetryEventSchema>;
export type WebPerformanceMetricName =
  (typeof webPerformanceMetricNames)[number];
export type WebPerformanceRouteGroup =
  (typeof webPerformanceRouteGroups)[number];
