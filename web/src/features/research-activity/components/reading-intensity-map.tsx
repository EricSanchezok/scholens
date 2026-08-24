"use client";

import { keyboardFocusRing } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import {
  activityIntensity,
  formatActivityDuration,
  relativeActivityIntensity,
} from "../format";
import type { PaperPageActivity } from "../types";
import { activityIntensityClasses } from "./activity-intensity";

export function ReadingIntensityMap({
  absolute = true,
  labels,
  locale,
  onPageSelect,
  pages,
}: {
  absolute?: boolean;
  labels: {
    annotations: (count: number) => string;
    page: (page: number) => string;
    pageRange: (startPage: number, endPage: number) => string;
    pageDetail: (values: {
      annotations: number;
      page: number;
      time: string;
      visits: number;
    }) => string;
    pageRangeDetail: (values: {
      annotations: number;
      endPage: number;
      startPage: number;
      time: string;
      visits: number;
    }) => string;
  };
  locale: string;
  onPageSelect?: (page: number) => void;
  pages: PaperPageActivity[];
}) {
  const peak = Math.max(0, ...pages.map((page) => page.activeMs));
  return (
    <ol className="grid grid-cols-[repeat(auto-fill,minmax(2.25rem,1fr))] gap-1.5">
      {pages.map((page) => {
        const intensity = absolute
          ? activityIntensity(page.activeMs)
          : relativeActivityIntensity(page.activeMs, peak);
        const segmentPeak = Math.max(1, ...page.verticalSegmentsMs);
        const isRange = page.pageEndNumber !== page.pageNumber;
        const detailValues = {
          annotations: page.annotationCount,
          time: formatActivityDuration(page.activeMs, locale),
          visits: page.visitCount,
        };
        const label = isRange
          ? labels.pageRangeDetail({
              ...detailValues,
              endPage: page.pageEndNumber,
              startPage: page.pageNumber,
            })
          : labels.pageDetail({
              ...detailValues,
              page: page.pageNumber,
            });
        return (
          <li className="min-w-0" key={page.pageNumber}>
            <button
              aria-label={label}
              className={cn(
                "relative flex min-h-10 w-full min-w-0 items-center justify-center rounded-[var(--radius-sm)] text-xs font-semibold tabular-nums",
                activityIntensityClasses[intensity],
                intensity >= 3 && "text-inverse",
                onPageSelect
                  ? "hover:outline-line-strong cursor-pointer hover:outline"
                  : "cursor-default",
                keyboardFocusRing,
              )}
              disabled={!onPageSelect}
              onClick={() => onPageSelect?.(page.navigationPageNumber)}
              title={label}
              type="button"
            >
              {page.activeMs > 0 ? (
                <span
                  aria-hidden
                  className="absolute inset-y-1 start-1 grid w-1.5 grid-rows-[repeat(20,minmax(0,1fr))] overflow-hidden rounded-full"
                >
                  {page.verticalSegmentsMs.map((milliseconds, index) => (
                    <span
                      className={
                        activityIntensityClasses[
                          absolute
                            ? activityIntensity(milliseconds)
                            : relativeActivityIntensity(
                                milliseconds,
                                segmentPeak,
                              )
                        ]
                      }
                      key={index}
                    />
                  ))}
                </span>
              ) : null}
              <span className="truncate ps-2 pe-1">
                {isRange
                  ? labels.pageRange(page.pageNumber, page.pageEndNumber)
                  : labels.page(page.pageNumber)}
              </span>
              {page.annotationCount > 0 ? (
                <span
                  aria-label={labels.annotations(page.annotationCount)}
                  className={cn(
                    "absolute end-1 top-1 size-1.5 rounded-full",
                    intensity >= 3 ? "bg-surface" : "bg-activity-peak",
                  )}
                />
              ) : null}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
