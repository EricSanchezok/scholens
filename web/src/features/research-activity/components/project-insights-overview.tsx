"use client";

import type { Route } from "next";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { LoadingState } from "@/components/feedback";
import { Button, focusSurfaceVariants } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import type {
  ProjectActivityEvent,
  ProjectResearchInsights,
  ResearchActivityRange,
} from "../types";
import {
  ActivityRangePicker,
  ActivityTrendChart,
  MetricStrip,
} from "./activity-visualizations";
import { ProjectPaperProgress } from "./project-paper-progress";

export function ProjectInsightsOverview({
  activity,
  activityError,
  error,
  insights,
  loading,
  onRetry,
  onActivityRetry,
  onRangeChange,
  projectId,
  range,
  toolbar,
}: {
  activity: ProjectActivityEvent[];
  activityError?: boolean;
  error?: boolean;
  insights?: ProjectResearchInsights;
  loading?: boolean;
  onRetry: () => void;
  onActivityRetry?: () => void;
  onRangeChange: (range: ResearchActivityRange) => void;
  projectId: string;
  range: ResearchActivityRange;
  toolbar?: React.ReactNode;
}) {
  const t = useTranslations("ResearchActivity");
  const locale = useLocale();
  const recordingSince = insights?.readingDataSince;
  const metricCollectionSince = insights?.activityHistoryCompleteSince;
  const header = (
    <section aria-labelledby="project-progress-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold" id="project-progress-title">
            {t("project.title")}
          </h2>
          <p className="text-secondary mt-1 text-sm leading-6">
            {t("project.description")}
          </p>
        </div>
        <div className="grid justify-items-end gap-2">
          {toolbar}
          <ActivityRangePicker
            labels={{
              "7d": t("ranges.7d"),
              "30d": t("ranges.30d"),
              "90d": t("ranges.90d"),
              all: t("ranges.all"),
              group: t("ranges.label"),
            }}
            onChange={(value) => onRangeChange(value as ResearchActivityRange)}
            ranges={["7d", "30d", "90d", "all"]}
            value={range}
          />
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
      </div>
    </section>
  );
  if (loading) {
    return (
      <div className="grid min-w-0 gap-8">
        {header}
        <section className="py-10" aria-label={t("project.loading")}>
          <LoadingState label={t("project.loading")} />
        </section>
      </div>
    );
  }
  if (error) {
    return (
      <div className="grid min-w-0 gap-8">
        {header}
        <section className="border-line-subtle border-b pb-6" role="alert">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold">
                {t("project.errorTitle")}
              </h2>
              <p className="text-secondary mt-1 text-sm">
                {t("project.errorDescription")}
              </p>
            </div>
            <Button onClick={onRetry} size="sm" variant="secondary">
              {t("actions.retry")}
            </Button>
          </div>
        </section>
      </div>
    );
  }
  if (!insights) return null;

  const metricLabels = {
    active_days: t("metrics.activeDays"),
    active_members: t("metrics.activeMembers"),
    active_ms: t("metrics.activeTime"),
    coverage_percent: t("metrics.coverage"),
    annotations: t("metrics.annotations"),
    conversations: t("metrics.conversations"),
    outputs: t("metrics.outputs"),
    papers_with_activity: t("metrics.papersWithActivity"),
    papers_added: t("metrics.papersAdded"),
    resolved_discussions: t("metrics.resolvedDiscussions"),
    shared_annotations: t("metrics.sharedAnnotations"),
    discussion_messages: t("metrics.discussionMessages"),
    substantive_pages: t("metrics.substantivePages"),
    sessions: t("metrics.sessions"),
    visible_ms: t("metrics.visibleTime"),
  };
  return (
    <div className="grid min-w-0 gap-8">
      {header}
      <div className="min-w-0">
        <div className="mt-6 grid gap-6 lg:grid-cols-2 lg:gap-10">
          <div>
            <h3 className="text-secondary mb-4 text-xs font-semibold">
              {t("project.mine")}
            </h3>
            <MetricStrip
              labels={metricLabels}
              locale={locale}
              metrics={insights.mine}
            />
          </div>
          <div className="border-line-subtle border-t pt-6 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-10">
            <h3 className="text-secondary mb-4 text-xs font-semibold">
              {t("project.team")}
            </h3>
            <MetricStrip
              labels={metricLabels}
              locale={locale}
              metrics={insights.team}
            />
            {!insights.teamReadingAvailable ? (
              <p className="text-muted mt-4 text-xs leading-5">
                {t("project.teamThreshold")}
              </p>
            ) : null}
          </div>
        </div>
        {insights.historyPartial && insights.activityHistoryCompleteSince ? (
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
      </div>

      {insights.daily.length > 0 ? (
        <section
          className="border-line-subtle min-w-0 border-t pt-7"
          aria-labelledby="project-trend-title"
        >
          <h2 className="text-base font-semibold" id="project-trend-title">
            {t("project.trend")}
          </h2>
          <p className="text-secondary mt-1 text-sm">
            {t("project.trendDescription")}
          </p>
          <div className="mt-3">
            <ActivityTrendChart
              days={insights.daily}
              labels={{
                active: t("chart.myReading"),
                chart: t("chart.projectLabel"),
                date: t("chart.date"),
                events: t("chart.events"),
                sessions: t("metrics.sessions"),
                singleDay: t("chart.singleDay"),
                table: t("chart.showTable"),
                team: t("chart.teamReading"),
                visible: t("metrics.visibleTime"),
              }}
              locale={locale}
              showTeam={insights.teamReadingAvailable}
            />
          </div>
        </section>
      ) : null}

      <section
        className="border-line-subtle min-w-0 border-t pt-7"
        aria-labelledby="project-papers-title"
      >
        <h2 className="text-base font-semibold" id="project-papers-title">
          {t("project.paperProgress")}
        </h2>
        <p className="text-secondary mt-1 text-sm">
          {t("project.paperProgressDescription")}
        </p>
        <div className="mt-3 min-w-0">
          <ProjectPaperProgress insights={insights} projectId={projectId} />
        </div>
      </section>

      {activityError || activity.length > 0 ? (
        <section
          className="border-line-subtle min-w-0 border-t pt-7"
          aria-labelledby="project-activity-title"
        >
          <h2 className="text-base font-semibold" id="project-activity-title">
            {t("project.activity")}
          </h2>
          {activityError ? (
            <div
              className="bg-subtle mt-3 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] p-3"
              role="alert"
            >
              <p className="text-secondary text-sm leading-6">
                {t("project.activityError")}
              </p>
              <Button
                onClick={onActivityRetry ?? onRetry}
                size="sm"
                variant="secondary"
              >
                {t("actions.retry")}
              </Button>
            </div>
          ) : (
            <ol className="divide-line-subtle mt-3 divide-y">
              {activity.map((event) => (
                <li className="flex gap-3 py-3" key={event.id}>
                  <span
                    aria-hidden
                    className="bg-activity-low mt-1.5 size-2 shrink-0 rounded-full"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm leading-5">
                      {t(`project.activityKinds.${event.kind}`)}
                    </span>
                    {event.documentId ? (
                      <Link
                        className={cn(
                          "mt-0.5 block rounded-[var(--radius-sm)] text-sm leading-5 font-medium hover:underline",
                          focusSurfaceVariants({ intent: "inline" }),
                        )}
                        href={
                          `/reader/${event.documentId}?project=${projectId}&panel=insights` as Route
                        }
                      >
                        {event.documentTitle ?? t("paper.untitled")}
                      </Link>
                    ) : null}
                    <span className="text-muted mt-0.5 block text-xs">
                      {event.actorName ? `${event.actorName} · ` : ""}
                      {new Intl.DateTimeFormat(locale, {
                        dateStyle: "medium",
                      }).format(new Date(event.occurredAt))}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>
      ) : null}
    </div>
  );
}
