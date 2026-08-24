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
] as const;

export const conversationPerformanceMetricNames = [
  "conversation_feedback",
  "conversation_accepted",
  "conversation_first_event",
  "conversation_first_content",
  "conversation_ready",
  "conversation_max_stall",
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

export const webTelemetryEventSchema = z.union([
  webPerformanceEventSchema,
  conversationPerformanceEventSchema,
]);

export type WebPerformanceEvent = z.infer<typeof webPerformanceEventSchema>;
export type ConversationPerformanceEvent = z.infer<
  typeof conversationPerformanceEventSchema
>;
export type ConversationPerformanceMetricName =
  (typeof conversationPerformanceMetricNames)[number];
export type WebTelemetryEvent = z.infer<typeof webTelemetryEventSchema>;
export type WebPerformanceMetricName =
  (typeof webPerformanceMetricNames)[number];
export type WebPerformanceRouteGroup =
  (typeof webPerformanceRouteGroups)[number];
