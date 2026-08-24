"use client";

import { useLocale, useTranslations } from "next-intl";

import { cn } from "@/lib/utilities/cn";
import { activityIntensityClasses } from "./activity-intensity";
import { formatActivityDuration, relativeActivityIntensity } from "../format";
import type { PaperActivitySummary } from "../types";

const MAX_COMPACT_ACTIVITY_CELLS = 12;

export function hasPaperActivityEvidence(summary: PaperActivitySummary) {
  return (
    summary.activeMs > 0 ||
    summary.pageBuckets.some((bucket) => bucket.activeMs > 0)
  );
}

function compactActivityBuckets(buckets: PaperActivitySummary["pageBuckets"]) {
  if (buckets.length <= MAX_COMPACT_ACTIVITY_CELLS) return buckets;
  return Array.from({ length: MAX_COMPACT_ACTIVITY_CELLS }, (_, index) => {
    const start = Math.floor(
      (index * buckets.length) / MAX_COMPACT_ACTIVITY_CELLS,
    );
    const end = Math.floor(
      ((index + 1) * buckets.length) / MAX_COMPACT_ACTIVITY_CELLS,
    );
    const group = buckets.slice(start, end);
    return {
      activeMs: group.reduce((total, bucket) => total + bucket.activeMs, 0),
      endPage: group.at(-1)!.endPage,
      startPage: group[0]!.startPage,
    };
  });
}

export function CompactPaperActivityTrail({
  summary,
}: {
  summary: PaperActivitySummary;
}) {
  const t = useTranslations("ResearchActivity.library");
  const locale = useLocale();
  const buckets = compactActivityBuckets(summary.pageBuckets);
  if (buckets.length === 0) return null;

  const hasKnownPageCount = summary.coveragePercent != null;
  const peak = Math.max(1, ...buckets.map((bucket) => bucket.activeMs));
  return (
    <span
      aria-label={t(
        hasKnownPageCount ? "distributionLabel" : "partialDistributionLabel",
      )}
      className="flex h-2 min-w-0 items-center gap-0.5 overflow-hidden"
      data-page-range-complete={hasKnownPageCount}
      data-paper-activity-trail=""
      role="img"
      title={t(
        hasKnownPageCount
          ? "distributionDescription"
          : "partialDistributionDescription",
      )}
    >
      {buckets.map((bucket) => {
        const pageRange =
          bucket.startPage === bucket.endPage
            ? String(bucket.startPage)
            : `${bucket.startPage}–${bucket.endPage}`;
        return (
          <span
            aria-hidden
            className={cn(
              "h-1.5 w-2.5 shrink-0 rounded-[1px]",
              activityIntensityClasses[
                relativeActivityIntensity(bucket.activeMs, peak)
              ],
            )}
            data-page-range={pageRange}
            data-paper-activity-cell=""
            key={`${bucket.startPage}-${bucket.endPage}`}
            title={t("bucketDescription", {
              duration: formatActivityDuration(bucket.activeMs, locale),
              pageRange,
            })}
          />
        );
      })}
      {hasKnownPageCount ? null : (
        <span
          aria-hidden
          className="text-muted -mt-0.5 ml-0.5 text-xs leading-none"
          data-paper-activity-continuation=""
        >
          …
        </span>
      )}
    </span>
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
