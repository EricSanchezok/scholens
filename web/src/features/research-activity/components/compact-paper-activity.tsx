"use client";

import { useLocale, useTranslations } from "next-intl";

import { formatActivityDuration, relativeActivityIntensity } from "../format";
import type { PaperActivitySummary } from "../types";

const intensityColors = [
  "transparent",
  "var(--color-activity-low)",
  "var(--color-activity-medium)",
  "var(--color-activity-high)",
  "var(--color-activity-peak)",
] as const;

export function hasPaperActivityEvidence(summary: PaperActivitySummary) {
  return (
    summary.activeMs > 0 ||
    summary.pageBuckets.some((bucket) => bucket.activeMs > 0)
  );
}

function activityTrailGradient(summary: PaperActivitySummary) {
  const peak = Math.max(
    1,
    ...summary.pageBuckets.map((bucket) => bucket.activeMs),
  );
  const colors = summary.pageBuckets.map(
    (bucket) =>
      intensityColors[relativeActivityIntensity(bucket.activeMs, peak)],
  );
  if (colors.length === 0) return "none";
  const stops = colors.map(
    (color, index) => `${color} ${((index + 1) / (colors.length + 1)) * 100}%`,
  );
  return `linear-gradient(90deg, transparent 0%, ${stops.join(", ")}, transparent 100%)`;
}

export function CompactPaperActivityTrail({
  summary,
}: {
  summary: PaperActivitySummary;
}) {
  const t = useTranslations("ResearchActivity.library");
  return (
    <span
      aria-label={t("distributionLabel")}
      className="block h-1.5 min-w-0 rounded-[1px]"
      data-paper-activity-trail=""
      role="img"
      style={{ backgroundImage: activityTrailGradient(summary) }}
      title={t("distributionDescription")}
    />
  );
}

export function CompactPaperActivityDuration({
  summary,
}: {
  summary: PaperActivitySummary;
}) {
  const t = useTranslations("ResearchActivity.library");
  const locale = useLocale();
  const duration = formatActivityDuration(summary.activeMs, locale);
  const coverage =
    summary.coveragePercent == null
      ? null
      : Math.round(summary.coveragePercent);
  const label =
    coverage == null
      ? t("durationOnly", { duration })
      : t("summary", { coverage, duration });
  return (
    <span
      aria-label={label}
      className="text-secondary block min-w-0 text-xs font-medium tabular-nums"
      data-paper-activity-duration=""
    >
      <span className="block truncate">{duration}</span>
      {coverage == null ? null : (
        <span className="text-muted mt-0.5 block truncate text-[0.6875rem] font-normal">
          {t("coverageValue", { coverage })}
        </span>
      )}
    </span>
  );
}
