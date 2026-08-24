"use client";

import type { Route } from "next";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { LoadingState } from "@/components/feedback";
import { Button, keyboardFocusRing } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import { formatActivityDuration } from "../format";
import type { PaperResearchInsights } from "../types";
import {
  ActivityLegend,
  ActivityTrendChart,
  MetricStrip,
  ReadingIntensityMap,
} from "./activity-visualizations";

export function PaperInsightsPanel({
  error,
  insights,
  loading,
  onPageSelect,
  onRetry,
  recordingEnabled,
  toolbar,
}: {
  error?: boolean;
  insights?: PaperResearchInsights;
  loading?: boolean;
  onPageSelect: (page: number) => void;
  onRetry: () => void;
  recordingEnabled?: boolean;
  toolbar?: React.ReactNode;
}) {
  const t = useTranslations("ResearchActivity");
  const locale = useLocale();
  const [relative, setRelative] = React.useState(false);
  const recordingSince = insights?.readingDataSince;
  const metricCollectionSince = insights?.activityHistoryCompleteSince;

  if (loading) {
    return (
      <div className="p-5">
        <LoadingState label={t("paper.loading")} />
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="grid min-h-full place-items-center p-5 text-center"
        role="alert"
      >
        <div className="max-w-xs">
          <p className="text-sm font-semibold">{t("paper.errorTitle")}</p>
          <p className="text-secondary mt-1 text-sm leading-6">
            {t("paper.errorDescription")}
          </p>
          <Button
            className="mt-4"
            onClick={onRetry}
            size="sm"
            variant="secondary"
          >
            {t("actions.retry")}
          </Button>
        </div>
      </div>
    );
  }
  if (
    !insights ||
    insights.summary.length === 0 ||
    insights.summary.every((metric) => metric.value === 0)
  ) {
    const recordingOff = recordingEnabled === false;
    const preferenceUnknown = recordingEnabled === undefined;
    return (
      <div className="grid min-h-full place-items-center p-5 text-center">
        <div className="max-w-xs">
          <p className="text-sm font-semibold">
            {recordingOff
              ? t("recording.offTitle")
              : preferenceUnknown
                ? t("recording.unknownTitle")
                : t("paper.emptyTitle")}
          </p>
          <p className="text-secondary mt-1 text-sm leading-6">
            {recordingOff
              ? t("recording.offEmptyDescription")
              : preferenceUnknown
                ? t("recording.unknownDescription")
                : t("paper.emptyDescription")}
          </p>
          {(recordingSince ?? metricCollectionSince) ? (
            <p className="text-muted mt-2 text-xs">
              {t(recordingSince ? "since" : "metricCollectionSince", {
                date: new Intl.DateTimeFormat(locale, {
                  dateStyle: "medium",
                }).format(
                  new Date(recordingSince ?? metricCollectionSince ?? 0),
                ),
              })}
            </p>
          ) : null}
          {recordingOff || preferenceUnknown ? (
            <Button asChild className="mt-4" size="sm" variant="secondary">
              <Link href={"/me/settings/display" as Route}>
                {t("actions.settings")}
              </Link>
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  const topPages = [...insights.pages]
    .filter((page) => page.activeMs > 0)
    .sort((left, right) => right.activeMs - left.activeMs)
    .slice(0, 5);
  const metricLabels = {
    active_ms: t("metrics.activeTime"),
    active_days: t("metrics.activeDays"),
    annotations: t("metrics.annotations"),
    coverage_percent: t("metrics.coverage"),
    sessions: t("metrics.sessions"),
    visible_ms: t("metrics.visibleTime"),
  };
  return (
    <div className="h-full overflow-y-auto" tabIndex={0}>
      <div className="grid gap-8 p-5">
        <section aria-labelledby="paper-insights-summary">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2
                className="text-base font-semibold"
                id="paper-insights-summary"
              >
                {t("paper.summary")}
              </h2>
              <p className="text-secondary mt-1 text-xs leading-5">
                {t("paper.approximate")}
              </p>
              <p className="text-muted mt-1 text-[0.6875rem]">
                {t("metricVersion", {
                  version: insights.metricDefinitionVersion,
                })}
              </p>
            </div>
            {(recordingSince ?? metricCollectionSince) ? (
              <p className="text-muted text-xs">
                {t(recordingSince ? "since" : "metricCollectionSince", {
                  date: new Intl.DateTimeFormat(locale, {
                    dateStyle: "medium",
                  }).format(
                    new Date(recordingSince ?? metricCollectionSince ?? 0),
                  ),
                })}
              </p>
            ) : null}
            {toolbar}
          </div>
          <div className="mt-5">
            <MetricStrip
              labels={metricLabels}
              locale={locale}
              metrics={insights.summary}
            />
          </div>
        </section>

        {insights.historyPartial && insights.activityHistoryCompleteSince ? (
          <p
            className="bg-subtle text-secondary rounded-[var(--radius-lg)] px-3 py-2 text-xs leading-5"
            role="note"
          >
            {t("partialHistory", {
              date: new Intl.DateTimeFormat(locale, {
                dateStyle: "medium",
              }).format(new Date(insights.activityHistoryCompleteSince)),
            })}
          </p>
        ) : null}

        {recordingEnabled === false ? (
          <div
            className="bg-subtle text-secondary flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] px-3 py-2 text-xs leading-5"
            role="note"
          >
            <span>{t("recording.offHistory")}</span>
            <Button asChild size="sm" variant="ghost">
              <Link href={"/me/settings/display" as Route}>
                {t("actions.settings")}
              </Link>
            </Button>
          </div>
        ) : null}

        <section aria-labelledby="paper-reading-map">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold" id="paper-reading-map">
                {t("paper.readingMap")}
              </h2>
              <p className="text-secondary mt-1 text-xs leading-5">
                {t("paper.readingMapDescription")}
              </p>
            </div>
            <div
              aria-label={t("paper.scaleLabel")}
              className="flex gap-1"
              role="group"
            >
              <Button
                aria-pressed={!relative}
                className="min-h-9 px-2"
                onClick={() => setRelative(false)}
                size="sm"
                variant={!relative ? "secondary" : "ghost"}
              >
                {t("paper.absolute")}
              </Button>
              <Button
                aria-pressed={relative}
                className="min-h-9 px-2"
                onClick={() => setRelative(true)}
                size="sm"
                variant={relative ? "secondary" : "ghost"}
              >
                {t("paper.relative")}
              </Button>
            </div>
          </div>
          <div className="mt-4">
            <ReadingIntensityMap
              absolute={!relative}
              labels={{
                annotations: (count) => t("paper.annotationCount", { count }),
                page: (page) => String(page),
                pageRange: (startPage, endPage) => `${startPage}–${endPage}`,
                pageDetail: (values) => t("paper.pageDetail", values),
                pageRangeDetail: (values) => t("paper.pageRangeDetail", values),
              }}
              locale={locale}
              onPageSelect={onPageSelect}
              pages={insights.pages}
            />
          </div>
          <div className="mt-3">
            <ActivityLegend
              labels={[
                t(relative ? "legend.relativeNone" : "legend.none"),
                t(relative ? "legend.relativeLow" : "legend.under15s"),
                t(relative ? "legend.relativeMedium" : "legend.from15sTo1m"),
                t(relative ? "legend.relativeHigh" : "legend.from1mTo3m"),
                t(relative ? "legend.relativePeak" : "legend.atLeast3m"),
              ]}
            />
          </div>
        </section>

        {insights.daily.length > 0 ? (
          <section aria-labelledby="paper-reading-trend">
            <h2 className="text-base font-semibold" id="paper-reading-trend">
              {t("paper.trend")}
            </h2>
            <div className="mt-3">
              <ActivityTrendChart
                days={insights.daily}
                labels={{
                  active: t("chart.myReading"),
                  chart: t("chart.paperLabel"),
                  date: t("chart.date"),
                  events: t("chart.events"),
                  sessions: t("metrics.sessions"),
                  table: t("chart.showTable"),
                  team: t("chart.teamReading"),
                  visible: t("metrics.visibleTime"),
                }}
                locale={locale}
              />
            </div>
          </section>
        ) : null}

        {topPages.length > 0 ? (
          <section aria-labelledby="paper-focus-pages">
            <h2 className="text-base font-semibold" id="paper-focus-pages">
              {t("paper.focusPages")}
            </h2>
            <ol className="divide-line-subtle mt-3 divide-y">
              {topPages.map((page) => (
                <li key={`${page.pageNumber}-${page.pageEndNumber}`}>
                  <button
                    className={cn(
                      "hover:bg-hover flex min-h-12 w-full items-center justify-between gap-3 rounded-[var(--radius-md)] px-2 text-left text-sm",
                      keyboardFocusRing,
                    )}
                    onClick={() => onPageSelect(page.navigationPageNumber)}
                    type="button"
                  >
                    <span className="min-w-0">
                      <span className="block truncate">
                        {page.pageNumber === page.pageEndNumber
                          ? t("paper.page", { page: page.pageNumber })
                          : t("paper.pages", {
                              endPage: page.pageEndNumber,
                              startPage: page.pageNumber,
                            })}
                      </span>
                      <span className="text-muted mt-0.5 block text-xs">
                        {t("paper.revisitContext", {
                          annotations: page.annotationCount,
                          visits: page.visitCount,
                        })}
                      </span>
                    </span>
                    <span className="text-secondary shrink-0 tabular-nums">
                      {formatActivityDuration(page.activeMs, locale)}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
      </div>
    </div>
  );
}
