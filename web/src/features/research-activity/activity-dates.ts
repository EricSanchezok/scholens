import type { ResearchActivityDay, ResearchActivityRange } from "./types";

const rangeDays: Partial<Record<ResearchActivityRange, number>> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
  "365d": 365,
};

function calendarDateInTimeZone(date: Date, zone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "2-digit",
    timeZone: zone,
    year: "numeric",
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}

function validCalendarDate(value: string | undefined) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) &&
    date.toISOString().slice(0, 10) === value
    ? value
    : undefined;
}

function addCalendarDays(value: string, days: number) {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function calendarDayStartInTimeZone(value: string, timeZone: string) {
  const target = Date.parse(`${value}T00:00:00Z`);
  let candidate = target;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const parts = new Intl.DateTimeFormat("en-US", {
      day: "2-digit",
      hour: "2-digit",
      hourCycle: "h23",
      minute: "2-digit",
      month: "2-digit",
      second: "2-digit",
      timeZone,
      year: "numeric",
    }).formatToParts(new Date(candidate));
    const numberPart = (type: Intl.DateTimeFormatPartTypes) =>
      Number(parts.find((part) => part.type === type)?.value);
    const observed = Date.UTC(
      numberPart("year"),
      numberPart("month") - 1,
      numberPart("day"),
      numberPart("hour"),
      numberPart("minute"),
      numberPart("second"),
    );
    const adjustment = target - observed;
    candidate += adjustment;
    if (adjustment === 0) break;
  }
  return candidate;
}

export function densifyResearchActivityDays({
  days,
  emptyDay = { activeMs: 0 },
  now = new Date(),
  range,
  readingDataSince,
  timeZone,
}: {
  days: ResearchActivityDay[];
  emptyDay?: Omit<ResearchActivityDay, "date">;
  now?: Date;
  range: ResearchActivityRange;
  readingDataSince?: string | null;
  timeZone: string;
}) {
  const today = calendarDateInTimeZone(now, timeZone);
  const knownDates = days
    .map((day) => validCalendarDate(day.date))
    .filter((date): date is string => Boolean(date))
    .sort();
  const parsedDataSince = readingDataSince
    ? new Date(readingDataSince)
    : undefined;
  const readingStart =
    parsedDataSince && Number.isFinite(parsedDataSince.getTime())
      ? calendarDateInTimeZone(parsedDataSince, timeZone)
      : undefined;
  const knownStart = knownDates[0];
  const collectionStart =
    readingStart && knownStart
      ? readingStart < knownStart
        ? readingStart
        : knownStart
      : (readingStart ?? knownStart);
  if (!collectionStart) return [];
  const selectedStart =
    range === "all"
      ? collectionStart
      : addCalendarDays(today, -Math.max(0, (rangeDays[range] ?? 1) - 1));
  const boundedStart =
    collectionStart > selectedStart ? collectionStart : selectedStart;
  // The server owns range semantics. Preserve an authoritative returned day
  // even when a response-time-zone or UTC-hour boundary places it just before
  // the browser's reconstructed calendar start.
  const start =
    knownStart && knownStart < boundedStart ? knownStart : boundedStart;
  if (start > today) return [];
  const byDate = new Map(days.map((day) => [day.date, day]));
  const result: ResearchActivityDay[] = [];
  for (let date = start; date <= today; date = addCalendarDays(date, 1)) {
    result.push(byDate.get(date) ?? { ...emptyDay, date });
  }
  return result;
}

export function historyIsPartial({
  activityHistoryCompleteSince,
  now = new Date(),
  range,
  timeZone,
}: {
  activityHistoryCompleteSince: string | null | undefined;
  now?: Date;
  range: ResearchActivityRange;
  timeZone: string;
}) {
  if (!activityHistoryCompleteSince || range === "all") return false;
  const completeSince = new Date(activityHistoryCompleteSince).getTime();
  if (!Number.isFinite(completeSince)) return false;
  const requestedStart = calendarDayStartInTimeZone(
    addCalendarDays(
      calendarDateInTimeZone(now, timeZone),
      -Math.max(0, (rangeDays[range] ?? 1) - 1),
    ),
    timeZone,
  );
  return Number.isFinite(requestedStart) && requestedStart < completeSince;
}
