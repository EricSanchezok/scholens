"use client";

import { keyboardFocusRing } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import { formatActivityDuration, relativeActivityIntensity } from "../format";
import type { ResearchActivityDay } from "../types";
import { activityIntensityClasses } from "./activity-intensity";

export function ActivityCalendar({
  days,
  labels,
  locale,
  tableInitiallyOpen = false,
}: {
  days: ResearchActivityDay[];
  labels: {
    chart: string;
    date: string;
    sessions: string;
    table: string;
    time: string;
    visible: string;
  };
  locale: string;
  tableInitiallyOpen?: boolean;
}) {
  if (days.length === 0) return null;
  const sorted = [...days].sort((left, right) =>
    left.date.localeCompare(right.date),
  );
  const first = new Date(`${sorted[0]?.date ?? "1970-01-01"}T00:00:00`);
  const leading = Array.from(
    { length: first.getDay() },
    (_, index) => `leading-${index}`,
  );
  const peak = Math.max(1, ...sorted.map((entry) => entry.activeMs));
  const showSessions = sorted.some((entry) => entry.sessionCount !== undefined);
  const showVisible = sorted.some((entry) => entry.visibleMs !== undefined);
  return (
    <div>
      <div
        aria-label={labels.chart}
        className="grid h-28 min-w-[42rem] grid-flow-col grid-rows-7 gap-1"
        role="img"
      >
        {leading.map((key) => (
          <span aria-hidden key={key} />
        ))}
        {sorted.map((day) => {
          const intensity = relativeActivityIntensity(day.activeMs, peak);
          const date = new Intl.DateTimeFormat(locale, {
            dateStyle: "medium",
          }).format(new Date(`${day.date}T00:00:00`));
          return (
            <span
              aria-hidden
              className={cn(
                "min-w-2 rounded-[2px]",
                activityIntensityClasses[intensity],
              )}
              key={day.date}
              title={`${date}: ${formatActivityDuration(day.activeMs, locale)}`}
            />
          );
        })}
      </div>
      <details className="mt-3" open={tableInitiallyOpen || undefined}>
        <summary
          className={cn(
            "hover:bg-hover inline-flex min-h-10 cursor-pointer items-center rounded-[var(--radius-md)] px-2 text-sm font-medium",
            keyboardFocusRing,
          )}
        >
          {labels.table}
        </summary>
        <div
          className="border-line mt-2 max-h-72 overflow-auto rounded-[var(--radius-md)] border"
          tabIndex={0}
        >
          <table className="w-full border-collapse text-left text-xs">
            <thead className="bg-subtle sticky top-0">
              <tr>
                <th className="px-3 py-2 font-medium">{labels.date}</th>
                <th className="px-3 py-2 font-medium">{labels.time}</th>
                {showVisible ? (
                  <th className="px-3 py-2 font-medium">{labels.visible}</th>
                ) : null}
                {showSessions ? (
                  <th className="px-3 py-2 font-medium">{labels.sessions}</th>
                ) : null}
              </tr>
            </thead>
            <tbody className="divide-line-subtle divide-y">
              {sorted.map((entry) => (
                <tr key={entry.date}>
                  <td className="px-3 py-2">
                    {new Intl.DateTimeFormat(locale, {
                      dateStyle: "medium",
                    }).format(new Date(`${entry.date}T00:00:00`))}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {formatActivityDuration(entry.activeMs, locale)}
                  </td>
                  {showVisible ? (
                    <td className="px-3 py-2 tabular-nums">
                      {entry.visibleMs == null
                        ? "—"
                        : formatActivityDuration(entry.visibleMs, locale)}
                    </td>
                  ) : null}
                  {showSessions ? (
                    <td className="px-3 py-2 tabular-nums">
                      {entry.sessionCount ?? "—"}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
