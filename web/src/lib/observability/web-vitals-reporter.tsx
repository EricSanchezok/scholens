"use client";

import { usePathname } from "next/navigation";
import { useReportWebVitals } from "next/web-vitals";
import * as React from "react";

import type { WebPerformanceMetricName } from "./web-performance-contract";
import { reportCommittedRoute, reportCoreWebVital } from "./web-performance";

const coreWebVitalNames = new Set(["CLS", "FCP", "INP", "LCP", "TTFB"]);

const handleWebVital: Parameters<typeof useReportWebVitals>[0] = (metric) => {
  if (!coreWebVitalNames.has(metric.name)) return;
  reportCoreWebVital(
    metric.name as Extract<
      WebPerformanceMetricName,
      "CLS" | "FCP" | "INP" | "LCP" | "TTFB"
    >,
    metric.value,
    metric.rating,
  );
};

export function WebPerformanceReporter() {
  const pathname = usePathname();
  useReportWebVitals(handleWebVital);
  React.useEffect(() => reportCommittedRoute(pathname), [pathname]);
  return null;
}
