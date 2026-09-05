"use client";

import type { Route } from "next";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { LoadingState } from "@/components/feedback";
import { Button, focusSurfaceVariants } from "@/components/ui";
import { ContextualLink } from "@/features/workspace-navigation";
import { cn } from "@/lib/utilities/cn";
import { formatActivityDuration } from "../format";
import type { PersonalResearchInsights, ResearchActivityRange } from "../types";
import {
  ActivityCalendar,
  ActivityLegend,
  ActivityRangePicker,
  ActivityTrendChart,
  MetricStrip,
} from "./activity-visualizations";

const ranges = ["30d", "90d", "365d", "all"] as const;

export function PersonalActivityDashboard({
  error,
  insights,
  loading,
  onRangeChange,
  onRetry,
  range,
  recordingEnabled,
  toolbar,
}: {
  error?: boolean;
  insights?: PersonalResearchInsights;
  loading?: boolean;
  onRangeChange: (range: ResearchActivityRange) => void;
  onRetry: () => void;
  range: ResearchActivityRange;
  recordingEnabled?: boolean;
  toolbar?: React.ReactNode;
}) {
  const t = useTranslations("ResearchActivity");
  const locale = useLocale();
  const controls = (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <ActivityRangePicker
        labels={{
          "30d": t("ranges.30d"),
          "90d": t("ranges.90d"),
          "365d": t("ranges.365d"),
          all: t("ranges.all"),
          group: t("ranges.label"),
        }}
        onChange={(value) => onRangeChange(value as ResearchActivityRange)}
        ranges={ranges}
        value={range}
      />
      {toolbar}
    </div>
  );
  if (loading) {
    return (
      <div className="grid min-w-0 gap-8">
        {controls}
        <div className="py-16">
          <LoadingState label={t("personal.loading")} />
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="grid min-w-0 gap-8">
        {controls}
        <div
          className="grid min-h-72 place-items-center text-center"
          role="alert"
        >
          <div className="max-w-sm">
            <h2 className="text-base font-semibold">
              {t("personal.errorTitle")}
            </h2>
            <p className="text-secondary mt-1 text-sm leading-6">
              {t("personal.errorDescription")}
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
      </div>
    );
  }

  const metricLabels = {
    active_days: t("metrics.activeDays"),
    active_ms: t("metrics.activeTime"),
    annotations: t("metrics.annotations"),
    conversations: t("metrics.conversations"),
    outputs: t("metrics.outputs"),
    papers_with_activity: t("metrics.papersWithActivity"),
    sessions: t("metrics.sessions"),
    substantive_pages: t("metrics.substantivePages"),
    visible_ms: t("metrics.visibleTime"),
  };
  const maximumProjectTime = Math.max(
    1,
    ...(insights?.projects.map((project) => project.activeMs) ?? []),
  );
  const recordingSince = insights?.readingDataSince;
  const metricCollectionSince = insights?.activityHistoryCompleteSince;

  return (
    <div className="grid min-w-0 gap-8">
      {controls}

      {!insights || insights.summary.every((metric) => metric.value === 0) ? (
        <div className="bg-subtle rounded-[var(--radius-xl)] px-5 py-12 text-center">
          <h2 className="text-base font-semibold">
            {recordingEnabled === false
              ? t("recording.offTitle")
              : recordingEnabled === undefined
                ? t("recording.unknownTitle")
                : t("personal.emptyTitle")}
          </h2>
          <p className="text-secondary mx-auto mt-1 max-w-md text-sm leading-6">
            {recordingEnabled === false
              ? t("recording.offEmptyDescription")
              : recordingEnabled === undefined
                ? t("recording.unknownDescription")
                : t("personal.emptyDescription")}
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
          {recordingEnabled !== true ? (
            <Button asChild className="mt-4" size="sm" variant="secondary">
              <Link
                href={"/me/settings/display?returnTo=/me/activity" as Route}
              >
                {t("actions.settings")}
              </Link>
            </Button>
          ) : null}
        </div>
      ) : (
        <>
          <section className="min-w-0" aria-labelledby="personal-summary-title">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2
                  className="text-lg font-semibold"
                  id="personal-summary-title"
                >
                  {t("personal.summary")}
                </h2>
                <p className="text-secondary mt-1 text-sm">
                  {t("personal.summaryDescription")}
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
            </div>
            <div className="mt-6">
              <MetricStrip
                labels={metricLabels}
                locale={locale}
                metrics={insights.summary}
              />
            </div>
            {insights.historyPartial &&
            insights.activityHistoryCompleteSince ? (
              <p
                className="bg-subtle text-secondary mt-5 rounded-[var(--radius-lg)] px-3 py-2 text-xs leading-5"
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
                className="bg-subtle text-secondary mt-5 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] px-3 py-2 text-xs leading-5"
                role="note"
              >
                <span>{t("recording.offHistory")}</span>
                <Button asChild size="sm" variant="ghost">
                  <Link
                    href={"/me/settings/display?returnTo=/me/activity" as Route}
                  >
                    {t("actions.settings")}
                  </Link>
                </Button>
              </div>
            ) : null}
          </section>

          {insights.daily.length > 0 ? (
            <section
              className="border-line-subtle min-w-0 border-t pt-7"
              aria-labelledby="personal-calendar-title"
            >
              <h2
                className="text-base font-semibold"
                id="personal-calendar-title"
              >
                {t("personal.calendar")}
              </h2>
              <p className="text-secondary mt-1 text-sm">
                {t("personal.calendarDescription")}
              </p>
              <div
                className={cn(
                  "mt-4 max-w-full min-w-0 overflow-x-auto pb-2",
                  focusSurfaceVariants({ intent: "scroll" }),
                )}
                tabIndex={0}
              >
                <ActivityCalendar
                  days={insights.daily}
                  labels={{
                    chart: t("personal.calendarLabel"),
                    date: t("chart.date"),
                    sessions: t("metrics.sessions"),
                    table: t("chart.showTable"),
                    time: t("chart.myReading"),
                    visible: t("metrics.visibleTime"),
                  }}
                  locale={locale}
                />
              </div>
              <div className="mt-3">
                <ActivityLegend
                  labels={[
                    t("legend.relativeNone"),
                    t("legend.relativeLow"),
                    t("legend.relativeMedium"),
                    t("legend.relativeHigh"),
                    t("legend.relativePeak"),
                  ]}
                />
              </div>
            </section>
          ) : null}

          {insights.daily.length > 0 ? (
            <section
              className="border-line-subtle min-w-0 border-t pt-7"
              aria-labelledby="personal-trend-title"
            >
              <h2 className="text-base font-semibold" id="personal-trend-title">
                {t("personal.trend")}
              </h2>
              <div className="mt-3">
                <ActivityTrendChart
                  days={insights.daily}
                  labels={{
                    active: t("chart.myReading"),
                    chart: t("chart.personalLabel"),
                    date: t("chart.date"),
                    events: t("chart.events"),
                    sessions: t("metrics.sessions"),
                    singleDay: t("chart.singleDay"),
                    table: t("chart.showTable"),
                    team: t("chart.teamReading"),
                    visible: t("metrics.visibleTime"),
                  }}
                  locale={locale}
                  showTable={false}
                />
              </div>
            </section>
          ) : null}

          <div className="border-line-subtle grid min-w-0 gap-8 border-t pt-7 lg:grid-cols-2 lg:gap-12">
            <section
              className="min-w-0"
              aria-labelledby="personal-projects-title"
            >
              <h2
                className="text-base font-semibold"
                id="personal-projects-title"
              >
                {t("personal.projects")}
              </h2>
              {insights.projects.length ? (
                <ol className="mt-4 grid gap-4">
                  {insights.projects.slice(0, 8).map((project) => {
                    const projectRange = range === "365d" ? "all" : range;
                    return (
                      <li key={project.projectId}>
                        <div className="flex items-baseline justify-between gap-3 text-sm">
                          <ContextualLink
                            className={cn(
                              "hover:text-secondary truncate rounded-[var(--radius-sm)] font-medium",
                              focusSurfaceVariants({ intent: "inline" }),
                            )}
                            href={
                              `/projects/${project.projectId}?range=${projectRange}` as Route
                            }
                            focusKey={project.projectId}
                            originKind="activity"
                          >
                            {project.title}
                          </ContextualLink>
                          <span className="text-secondary shrink-0 tabular-nums">
                            {formatActivityDuration(project.activeMs, locale)}
                          </span>
                        </div>
                        <p className="text-muted mt-0.5 text-xs tabular-nums">
                          {t("personal.sessionContext", {
                            count: project.sessionCount,
                          })}
                        </p>
                        <div className="bg-activity-empty mt-1.5 h-1.5 overflow-hidden rounded-full">
                          <span
                            aria-hidden
                            className="bg-activity-peak block h-full rounded-full"
                            style={{
                              width: `${Math.max(2, (project.activeMs / maximumProjectTime) * 100)}%`,
                            }}
                          />
                        </div>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <p className="text-muted mt-4 text-sm">
                  {t("personal.noProjects")}
                </p>
              )}
            </section>

            <section
              className="min-w-0"
              aria-labelledby="personal-papers-title"
            >
              <h2
                className="text-base font-semibold"
                id="personal-papers-title"
              >
                {t("personal.papers")}
              </h2>
              {insights.papers.length ? (
                <ol className="divide-line-subtle mt-2 divide-y">
                  {insights.papers.slice(0, 8).map((paper) => (
                    <li key={paper.documentId}>
                      <ContextualLink
                        className={cn(
                          "hover:bg-hover flex min-h-14 items-center justify-between gap-3 rounded-[var(--radius-md)] px-2 py-2",
                          focusSurfaceVariants({ intent: "neutral" }),
                        )}
                        href={
                          `/reader/${paper.documentId}?panel=insights` as Route
                        }
                        focusKey={paper.documentId}
                        originKind="activity"
                      >
                        <span className="min-w-0">
                          <span className="line-clamp-2 text-sm font-medium">
                            {paper.title ?? t("paper.untitled")}
                          </span>
                          <span className="text-muted mt-0.5 block text-xs tabular-nums">
                            {paper.lastReadAt
                              ? t("personal.paperContext", {
                                  count: paper.sessionCount,
                                  date: new Intl.DateTimeFormat(locale, {
                                    dateStyle: "medium",
                                  }).format(new Date(paper.lastReadAt)),
                                })
                              : t("personal.sessionContext", {
                                  count: paper.sessionCount,
                                })}
                          </span>
                        </span>
                        <span className="text-secondary shrink-0 text-xs tabular-nums">
                          {formatActivityDuration(paper.activeMs, locale)}
                        </span>
                      </ContextualLink>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-muted mt-4 text-sm">
                  {t("personal.noPapers")}
                </p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
