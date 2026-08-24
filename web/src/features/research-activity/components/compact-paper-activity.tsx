"use client";

import { useLocale, useTranslations } from "next-intl";

import { cn } from "@/lib/utilities/cn";
import { formatActivityDuration, relativeActivityIntensity } from "../format";
import type { PaperActivitySummary } from "../types";

const bucketClasses = [
  "bg-activity-empty",
  "bg-activity-low",
  "bg-activity-medium",
  "bg-activity-high",
  "bg-activity-peak",
] as const;

export function hasPaperActivityEvidence(summary: PaperActivitySummary) {
  return (
    summary.activeMs > 0 ||
    summary.pageBuckets.some((bucket) => bucket.activeMs > 0)
  );
}

export function CompactPaperActivity({
  summary,
}: {
  summary: PaperActivitySummary;
}) {
  const t = useTranslations("ResearchActivity");
  const locale = useLocale();
  const peak = Math.max(
    1,
    ...summary.pageBuckets.map((bucket) => bucket.activeMs),
  );
  const duration = formatActivityDuration(summary.activeMs, locale);
  const coverage =
    summary.coveragePercent == null
      ? null
      : Math.round(summary.coveragePercent);
  const label =
    coverage == null
      ? t("library.durationOnly", { duration })
      : t("library.summary", { coverage, duration });
  return (
    <span aria-label={label} className="block min-w-0">
      <span
        aria-hidden
        className="flex h-1 min-w-0 gap-px overflow-hidden rounded-full"
      >
        {summary.pageBuckets.map((bucket) => (
          <span
            className={cn(
              "min-w-px flex-1",
              bucketClasses[relativeActivityIntensity(bucket.activeMs, peak)],
            )}
            key={`${bucket.startPage}-${bucket.endPage}`}
          />
        ))}
      </span>
      <span className="text-muted mt-1 block truncate text-[0.6875rem] tabular-nums">
        {coverage == null
          ? t("library.durationOnly", { duration })
          : t("library.durationAndCoverage", { coverage, duration })}
      </span>
    </span>
  );
}
