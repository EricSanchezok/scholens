"use client";

import { usePathname } from "next/navigation";
import * as React from "react";

import { clientEnvironment } from "@/lib/env/client";
import type {
  ConversationPerformanceEvent,
  ConversationPerformanceMetricName,
  PdfRenderErrorEvent,
  ReaderAnnotationMetricName,
  WebTelemetryEvent,
  WebPerformanceEvent,
  WebPerformanceMetricName,
  WebPerformanceRouteGroup,
} from "./web-performance-contract";

type NetworkInformation = {
  effectiveType?: "slow-2g" | "2g" | "3g" | "4g";
  saveData?: boolean;
};

type PendingNavigation = {
  feedbackReported: boolean;
  fromRoute: WebPerformanceRouteGroup;
  startedAt: number;
  toPathname: string;
  toRoute: WebPerformanceRouteGroup;
};

let pendingNavigation: PendingNavigation | undefined;
let completedNavigation:
  Pick<PendingNavigation, "fromRoute" | "startedAt" | "toRoute"> | undefined;
const navigationListeners = new Set<() => void>();

function notifyNavigationListeners() {
  navigationListeners.forEach((listener) => listener());
}

export function performanceRouteGroup(
  pathname: string,
): WebPerformanceRouteGroup {
  if (pathname === "/") return "home";
  if (pathname === "/library") return "library";
  if (pathname === "/projects") return "projects";
  if (/^\/projects\/[^/]+$/.test(pathname)) return "project-detail";
  if (/^\/reader\/[^/]+$/.test(pathname)) return "reader";
  if (pathname === "/login") return "login";
  if (pathname === "/docs") return "documentation";
  return "unknown";
}

function browserContext(): Pick<
  WebTelemetryEvent,
  "device_class" | "effective_type" | "save_data"
> {
  const connection = (
    navigator as Navigator & { connection?: NetworkInformation }
  ).connection;
  const effectiveType: NonNullable<WebPerformanceEvent["effective_type"]> =
    connection?.effectiveType ?? "unknown";
  return {
    device_class: window.matchMedia("(max-width: 63.999rem)").matches
      ? ("mobile" as const)
      : ("desktop" as const),
    effective_type: effectiveType,
    save_data: connection?.saveData,
  };
}

type BrowserContextFields =
  "device_class" | "effective_type" | "event_id" | "release" | "save_data";
type BrowserTelemetryPayload<T> = T extends WebTelemetryEvent
  ? Omit<T, BrowserContextFields>
  : never;

function reportWebTelemetry(event: BrowserTelemetryPayload<WebTelemetryEvent>) {
  if (typeof window === "undefined") return;
  const body: WebTelemetryEvent = {
    ...event,
    ...browserContext(),
    event_id: crypto.randomUUID(),
    release: clientEnvironment.NEXT_PUBLIC_RELEASE_SHA,
  } as WebTelemetryEvent;
  void fetch("/__telemetry/web-performance", {
    body: JSON.stringify(body),
    credentials: "omit",
    headers: { "content-type": "application/json" },
    keepalive: true,
    method: "POST",
  }).catch(() => undefined);
}

type PdfRenderErrorPayload = Omit<PdfRenderErrorEvent, BrowserContextFields>;

function reportWebPerformance(
  event: BrowserTelemetryPayload<WebPerformanceEvent>,
) {
  reportWebTelemetry(event);
}

export function reportConversationPerformance(
  metric: ConversationPerformanceMetricName,
  value: number,
  streamKind?: ConversationPerformanceEvent["stream_kind"],
) {
  if (typeof window === "undefined") return;
  reportWebTelemetry({
    metric,
    stream_kind: streamKind,
    to_route: performanceRouteGroup(window.location.pathname),
    value: Math.max(0, value),
  });
}

export function reportPdfRenderError(
  payload: Omit<PdfRenderErrorPayload, "metric" | "to_route">,
) {
  if (typeof window === "undefined") return;
  reportWebTelemetry({
    ...payload,
    metric: "pdf_render_error",
    to_route: "reader",
  });
}

/** Low-cardinality Reader annotation metrics; never include quote text or IDs. */
export function reportReaderAnnotationMetric(
  metric: ReaderAnnotationMetricName,
  value = 1,
) {
  if (typeof window === "undefined") return;
  reportWebPerformance({
    metric,
    navigation_kind: "soft",
    to_route: "reader",
    value: Math.max(0, value),
  });
}

export function reportCoreWebVital(
  metric: Extract<
    WebPerformanceMetricName,
    "CLS" | "FCP" | "INP" | "LCP" | "TTFB"
  >,
  value: number,
  rating?: "good" | "needs-improvement" | "poor",
) {
  reportWebPerformance({
    metric,
    navigation_kind: "hard",
    rating,
    to_route: performanceRouteGroup(window.location.pathname),
    value: Math.max(0, value),
  });
}

export function beginRouteNavigation(href: string) {
  if (typeof window === "undefined") return;
  const target = new URL(href, window.location.href);
  if (
    target.origin !== window.location.origin ||
    target.pathname === window.location.pathname
  ) {
    return;
  }
  pendingNavigation = {
    feedbackReported: false,
    fromRoute: performanceRouteGroup(window.location.pathname),
    startedAt: performance.now(),
    toPathname: target.pathname,
    toRoute: performanceRouteGroup(target.pathname),
  };
  completedNavigation = undefined;
  notifyNavigationListeners();
}

export function useRouteNavigationPending(href: string) {
  const getSnapshot = React.useCallback(() => {
    if (typeof window === "undefined" || !pendingNavigation) return false;
    return (
      pendingNavigation.toPathname ===
      new URL(href, window.location.href).pathname
    );
  }, [href]);
  return React.useSyncExternalStore(
    React.useCallback((listener) => {
      navigationListeners.add(listener);
      return () => navigationListeners.delete(listener);
    }, []),
    getSnapshot,
    () => false,
  );
}

export function reportRouteNavigationFeedback() {
  const navigation = pendingNavigation;
  if (!navigation || navigation.feedbackReported) return;
  navigation.feedbackReported = true;
  window.requestAnimationFrame(() => {
    reportWebPerformance({
      from_route: navigation.fromRoute,
      metric: "route_feedback",
      navigation_kind: "soft",
      to_route: navigation.toRoute,
      value: performance.now() - navigation.startedAt,
    });
  });
}

export function usePrimaryContentReady(ready: boolean) {
  const pathname = usePathname();
  const reportedPathname = React.useRef<string | undefined>(undefined);
  React.useEffect(() => {
    if (!ready || reportedPathname.current === pathname) return;
    const toRoute = performanceRouteGroup(pathname);
    const navigation =
      completedNavigation?.toRoute === toRoute
        ? completedNavigation
        : undefined;
    reportWebPerformance({
      from_route: navigation?.fromRoute,
      metric: "primary_content",
      navigation_kind: navigation ? "soft" : "hard",
      to_route: toRoute,
      value: performance.now() - (navigation?.startedAt ?? 0),
    });
    reportedPathname.current = pathname;
  }, [pathname, ready]);
}

export function reportCommittedRoute(pathname: string) {
  const navigation = pendingNavigation;
  const toRoute = performanceRouteGroup(pathname);
  if (!navigation || navigation.toRoute !== toRoute) return;
  reportWebPerformance({
    from_route: navigation.fromRoute,
    metric: "route_commit",
    navigation_kind: "soft",
    to_route: navigation.toRoute,
    value: performance.now() - navigation.startedAt,
  });
  completedNavigation = navigation;
  pendingNavigation = undefined;
  notifyNavigationListeners();
}
