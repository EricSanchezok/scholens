"use client";

import type { Route } from "next";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Button, Skeleton, focusSurfaceVariants } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import { formatActivityDuration } from "../format";
import type { PersonalResearchInsights } from "../types";

const HOME_ACTIVITY_WINDOW_DAYS = 30;

export function HomeActivitySnapshot({
  error,
  insights,
  loading,
  onRetry,
  recordingEnabled,
}: {
  error?: boolean;
  insights?: PersonalResearchInsights;
  loading?: boolean;
  onRetry: () => void;
  recordingEnabled?: boolean;
}) {
  const t = useTranslations("ResearchActivity.home");
  const locale = useLocale();
  if (loading) {
    return (
      <section
        aria-label={t("title")}
        className="bg-subtle rounded-[var(--radius-xl)] p-4"
        role="status"
      >
        <Skeleton className="h-4 w-36" />
        <Skeleton className="mt-4 h-12 w-full" />
      </section>
    );
  }
  if (error) {
    return (
      <section
        className="bg-subtle flex min-h-24 flex-wrap items-center justify-between gap-3 rounded-[var(--radius-xl)] p-4"
        role="alert"
      >
        <div>
          <h2 className="text-sm font-semibold">{t("title")}</h2>
          <p className="text-secondary mt-1 text-xs">{t("error")}</p>
        </div>
        <div className="flex gap-1">
          <Button onClick={onRetry} size="sm" variant="ghost">
            {t("retry")}
          </Button>
          <Button asChild size="sm" variant="secondary">
            <Link href={"/me/activity" as Route}>{t("open")}</Link>
          </Button>
        </div>
      </section>
    );
  }

  const activeMs =
    insights?.summary.find((metric) => metric.key === "active_ms")?.value ?? 0;
  const activeDays =
    insights?.summary.find((metric) => metric.key === "active_days")?.value ??
    0;
  const papers =
    insights?.summary.find((metric) => metric.key === "papers_with_activity")
      ?.value ?? 0;
  const annotations =
    insights?.summary.find((metric) => metric.key === "annotations")?.value ??
    0;
  const questions =
    insights?.summary.find((metric) => metric.key === "conversations")?.value ??
    0;
  const outputs =
    insights?.summary.find((metric) => metric.key === "outputs")?.value ?? 0;
  const hasEvidence =
    insights?.summary.some((metric) => metric.value > 0) ?? false;
  const processFacts = [
    annotations > 0 ? t("annotations", { count: annotations }) : null,
    questions > 0 ? t("questions", { count: questions }) : null,
    outputs > 0 ? t("outputs", { count: outputs }) : null,
  ].filter((value): value is string => value !== null);
  const peak = Math.max(
    1,
    ...(insights?.daily.map((day) => day.activeMs) ?? []),
  );
  const recentDays = insights?.daily.slice(-HOME_ACTIVITY_WINDOW_DAYS) ?? [];
  const activityWindow = [
    ...Array.from(
      { length: HOME_ACTIVITY_WINDOW_DAYS - recentDays.length },
      () => null,
    ),
    ...recentDays,
  ];
  const settingsDestination = !hasEvidence && recordingEnabled !== true;
  return (
    <Link
      className={cn(
        "bg-subtle hover:bg-hover active:bg-pressed block rounded-[var(--radius-xl)] p-4 text-left",
        focusSurfaceVariants({ intent: "neutral" }),
      )}
      href={
        (settingsDestination
          ? "/me/settings/display?returnTo=/"
          : "/me/activity") as Route
      }
    >
      <span className="flex items-center justify-between gap-3">
        <span>
          <span className="block text-sm font-semibold">{t("title")}</span>
          <span className="text-secondary mt-0.5 block text-xs">
            {t("period")}
          </span>
        </span>
        <span className="text-secondary text-xs font-medium">
          {settingsDestination ? t("settings") : t("open")}
        </span>
      </span>
      {hasEvidence ? (
        <span className="mt-4 grid gap-3">
          {activeMs > 0 || activeDays > 0 || papers > 0 ? (
            <span className="grid min-w-0 grid-cols-2 items-end gap-4 sm:grid-cols-[auto_auto_1fr]">
              {activeMs > 0 ? (
                <span>
                  <span className="block text-xl font-semibold tabular-nums">
                    {formatActivityDuration(activeMs, locale)}
                  </span>
                  <span className="text-muted block text-[0.6875rem]">
                    {t("active")}
                  </span>
                </span>
              ) : null}
              {activeDays > 0 || papers > 0 ? (
                <span className="text-secondary text-xs tabular-nums">
                  {t("daysAndPapers", { days: activeDays, papers })}
                </span>
              ) : null}
              {activeMs > 0 ? (
                <span
                  aria-hidden
                  className="border-line-subtle col-span-2 grid h-10 min-w-0 items-end gap-px border-b sm:col-span-1 sm:w-full sm:max-w-lg sm:justify-self-end"
                  data-visualization="home-activity-trend"
                  style={{
                    gridTemplateColumns: `repeat(${HOME_ACTIVITY_WINDOW_DAYS}, minmax(0, 1fr))`,
                  }}
                >
                  {activityWindow.map((day, index) => (
                    <span
                      className={cn(
                        "w-1.5 min-w-px justify-self-center rounded-t-[1px]",
                        day === null
                          ? "h-0"
                          : day.activeMs === 0
                            ? "bg-activity-empty h-px"
                            : "bg-activity-peak min-h-1",
                      )}
                      data-activity-slot={
                        day === null
                          ? "missing"
                          : day.activeMs === 0
                            ? "empty"
                            : "active"
                      }
                      key={day?.date ?? `missing-${index}`}
                      style={{
                        height:
                          day !== null && day.activeMs > 0
                            ? `${Math.max(4, (day.activeMs / peak) * 100)}%`
                            : undefined,
                      }}
                    />
                  ))}
                </span>
              ) : null}
            </span>
          ) : null}
          {processFacts.length > 0 ? (
            <span
              className="text-secondary flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums"
              role="list"
            >
              {processFacts.map((fact) => (
                <span key={fact} role="listitem">
                  {fact}
                </span>
              ))}
            </span>
          ) : activeMs === 0 && activeDays === 0 && papers === 0 ? (
            <span className="text-secondary text-sm">{t("recorded")}</span>
          ) : null}
          {recordingEnabled === false ? (
            <span className="text-muted text-xs leading-5">
              {t("recordingOffHistory")}
            </span>
          ) : null}
        </span>
      ) : (
        <span className="text-secondary mt-4 block text-sm leading-6">
          {recordingEnabled === false
            ? t("recordingOff")
            : recordingEnabled === undefined
              ? t("preferenceUnknown")
              : t("empty")}
        </span>
      )}
    </Link>
  );
}
