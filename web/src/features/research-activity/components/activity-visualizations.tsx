"use client";

import { Button, focusSurfaceVariants } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import { formatActivityDuration, formatActivityMetric } from "../format";
import type { ResearchActivityDay, ResearchActivityMetric } from "../types";
import { activityIntensityClasses } from "./activity-intensity";

export { ActivityCalendar } from "./activity-calendar";
export { ReadingIntensityMap } from "./reading-intensity-map";

export function MetricStrip({
  labels,
  locale,
  metrics,
}: {
  labels: Record<string, string>;
  locale: string;
  metrics: ResearchActivityMetric[];
}) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
      {metrics.map((metric) => (
        <div className="min-w-0" key={metric.key}>
          <dt className="text-secondary text-xs leading-5">
            {labels[metric.key] ?? metric.key}
          </dt>
          <dd className="mt-1 text-xl leading-7 font-semibold tracking-[-0.02em] tabular-nums">
            {formatActivityMetric(metric.value, metric.unit, locale)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function ActivityLegend({
  labels,
}: {
  labels: [string, string, string, string, string];
}) {
  return (
    <div className="text-secondary flex flex-wrap gap-x-3 gap-y-1 text-xs">
      {labels.map((label, index) => (
        <span className="inline-flex items-center gap-1.5" key={label}>
          <span
            aria-hidden
            className={cn(
              "size-2.5 rounded-[2px]",
              activityIntensityClasses[index],
            )}
          />
          {label}
        </span>
      ))}
    </div>
  );
}

export function activityTrendPath(
  values: Array<number | null>,
  width: number,
  height: number,
  maximum: number,
) {
  if (values.length === 0) return "";
  let connected = false;
  return values
    .map((value, index) => {
      if (value == null) {
        connected = false;
        return "";
      }
      const { x, y } = activityTrendPoint(
        value,
        index,
        values.length,
        width,
        height,
        maximum,
      );
      const command = connected ? "L" : "M";
      connected = true;
      return `${command}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

function activityTrendPoint(
  value: number,
  index: number,
  length: number,
  width: number,
  height: number,
  maximum: number,
) {
  return {
    x: length === 1 ? width / 2 : (index / (length - 1)) * width,
    y: height - (value / Math.max(1, maximum)) * height,
  };
}

export function ActivityTrendChart({
  days,
  labels,
  locale,
  showTable = true,
  showTeam = false,
  tableInitiallyOpen = false,
}: {
  days: ResearchActivityDay[];
  labels: {
    active: string;
    chart: string;
    date: string;
    events: string;
    sessions: string;
    table: string;
    team: string;
    visible: string;
  };
  locale: string;
  showTable?: boolean;
  showTeam?: boolean;
  tableInitiallyOpen?: boolean;
}) {
  const width = 720;
  const height = 176;
  const maximum = Math.max(
    1,
    ...days.map((day) =>
      Math.max(
        day.activeMs,
        typeof day.teamActiveMs === "number" ? day.teamActiveMs : 0,
      ),
    ),
  );
  const personalPath = activityTrendPath(
    days.map((day) => day.activeMs),
    width,
    height,
    maximum,
  );
  const teamPath = activityTrendPath(
    days.map((day) => day.teamActiveMs ?? null),
    width,
    height,
    maximum,
  );
  const showEvents = days.some((day) => day.sharedEventCount !== undefined);
  const showSessions = days.some((day) => day.sessionCount !== undefined);
  const showVisible = days.some((day) => day.visibleMs !== undefined);

  return (
    <div className="min-w-0">
      <svg
        aria-label={labels.chart}
        className="h-48 w-full overflow-visible"
        data-visualization="activity-trend"
        preserveAspectRatio="none"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        {[0, 1, 2, 3, 4].map((line) => (
          <line
            key={line}
            stroke="var(--color-border-subtle)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
            x1="0"
            x2={width}
            y1={(line / 4) * height}
            y2={(line / 4) * height}
          />
        ))}
        {showTeam && teamPath ? (
          <path
            d={teamPath}
            fill="none"
            stroke="var(--color-research-activity-secondary)"
            strokeDasharray="5 5"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
        {personalPath ? (
          <path
            d={personalPath}
            fill="none"
            stroke="var(--color-research-activity-peak)"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2.5"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
        {showTeam
          ? days.map((day, index) => {
              if (day.teamActiveMs == null) return null;
              const point = activityTrendPoint(
                day.teamActiveMs,
                index,
                days.length,
                width,
                height,
                maximum,
              );
              return (
                <circle
                  aria-hidden
                  cx={point.x}
                  cy={point.y}
                  data-series="team"
                  fill="var(--color-research-activity-secondary)"
                  key={`team-${day.date}`}
                  r="2.5"
                  vectorEffect="non-scaling-stroke"
                />
              );
            })
          : null}
        {days.map((day, index) => {
          const point = activityTrendPoint(
            day.activeMs,
            index,
            days.length,
            width,
            height,
            maximum,
          );
          return (
            <circle
              aria-hidden
              cx={point.x}
              cy={point.y}
              data-series="personal"
              fill="var(--color-research-activity-peak)"
              key={`personal-${day.date}`}
              r="3"
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </svg>
      {days.length > 0 ? (
        <div className="text-muted mt-1 flex justify-between gap-3 text-xs tabular-nums">
          <span>
            {new Intl.DateTimeFormat(locale, {
              day: "numeric",
              month: "short",
            }).format(new Date(`${days[0]?.date}T00:00:00`))}
          </span>
          <span>
            {new Intl.DateTimeFormat(locale, {
              day: "numeric",
              month: "short",
            }).format(new Date(`${days.at(-1)?.date}T00:00:00`))}
          </span>
        </div>
      ) : null}
      <div className="text-secondary mt-2 flex flex-wrap gap-4 text-xs">
        <span className="inline-flex items-center gap-2">
          <span aria-hidden className="bg-activity-peak h-0.5 w-5" />
          {labels.active}
        </span>
        {showTeam ? (
          <span className="inline-flex items-center gap-2">
            <span
              aria-hidden
              className="border-activity-secondary w-5 border-t-2 border-dashed"
            />
            {labels.team}
          </span>
        ) : null}
      </div>
      {showTable ? (
        <details className="mt-4" open={tableInitiallyOpen || undefined}>
          <summary
            className={cn(
              "hover:bg-hover inline-flex min-h-10 cursor-pointer items-center rounded-[var(--radius-md)] px-2 text-sm font-medium",
              focusSurfaceVariants({ intent: "neutral" }),
            )}
          >
            {labels.table}
          </summary>
          <div
            className={cn(
              "border-line mt-2 max-h-72 overflow-auto rounded-[var(--radius-md)] border",
              focusSurfaceVariants({ intent: "scroll" }),
            )}
            tabIndex={0}
          >
            <table className="w-full min-w-[28rem] border-collapse text-left text-xs">
              <thead className="bg-subtle sticky top-0">
                <tr>
                  <th className="px-3 py-2 font-medium">{labels.date}</th>
                  <th className="px-3 py-2 font-medium">{labels.active}</th>
                  {showTeam ? (
                    <th className="px-3 py-2 font-medium">{labels.team}</th>
                  ) : null}
                  {showVisible ? (
                    <th className="px-3 py-2 font-medium">{labels.visible}</th>
                  ) : null}
                  {showSessions ? (
                    <th className="px-3 py-2 font-medium">{labels.sessions}</th>
                  ) : null}
                  {showEvents ? (
                    <th className="px-3 py-2 font-medium">{labels.events}</th>
                  ) : null}
                </tr>
              </thead>
              <tbody className="divide-line-subtle divide-y">
                {days.map((day) => (
                  <tr key={day.date}>
                    <td className="px-3 py-2">
                      {new Intl.DateTimeFormat(locale).format(
                        new Date(`${day.date}T00:00:00`),
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {formatActivityDuration(day.activeMs, locale)}
                    </td>
                    {showTeam ? (
                      <td className="px-3 py-2 tabular-nums">
                        {day.teamActiveMs == null
                          ? "—"
                          : formatActivityDuration(day.teamActiveMs, locale)}
                      </td>
                    ) : null}
                    {showVisible ? (
                      <td className="px-3 py-2 tabular-nums">
                        {day.visibleMs == null
                          ? "—"
                          : formatActivityDuration(day.visibleMs, locale)}
                      </td>
                    ) : null}
                    {showSessions ? (
                      <td className="px-3 py-2 tabular-nums">
                        {day.sessionCount ?? "—"}
                      </td>
                    ) : null}
                    {showEvents ? (
                      <td className="px-3 py-2 tabular-nums">
                        {day.sharedEventCount ?? "—"}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </div>
  );
}

export function ActivityRangePicker({
  labels,
  onChange,
  ranges,
  value,
}: {
  labels: Record<string, string>;
  onChange: (range: string) => void;
  ranges: readonly string[];
  value: string;
}) {
  return (
    <div
      aria-label={labels.group}
      className="flex flex-wrap gap-1"
      role="group"
    >
      {ranges.map((range) => (
        <Button
          aria-pressed={range === value}
          className="min-h-9 px-3"
          key={range}
          onClick={() => onChange(range)}
          size="sm"
          variant={range === value ? "secondary" : "ghost"}
        >
          {labels[range] ?? range}
        </Button>
      ))}
    </div>
  );
}
