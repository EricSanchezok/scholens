export function formatActivityDuration(milliseconds: number, locale: string) {
  const duration = Math.max(0, milliseconds);
  if (duration > 0 && duration < 60_000) {
    return new Intl.NumberFormat(locale, {
      maximumFractionDigits: 0,
      style: "unit",
      unit: "second",
      unitDisplay: "short",
    }).format(Math.max(1, Math.round(duration / 1_000)));
  }
  const minutes = Math.max(0, Math.round(milliseconds / 60_000));
  if (minutes < 60) {
    return new Intl.NumberFormat(locale, {
      maximumFractionDigits: 0,
      style: "unit",
      unit: "minute",
      unitDisplay: "short",
    }).format(minutes);
  }
  const hours = minutes / 60;
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: 1,
    style: "unit",
    unit: "hour",
    unitDisplay: "short",
  }).format(hours);
}

export function formatActivityMetric(
  value: number,
  unit: "count" | "milliseconds" | "percent",
  locale: string,
) {
  if (unit === "milliseconds") return formatActivityDuration(value, locale);
  if (unit === "percent") {
    return new Intl.NumberFormat(locale, {
      maximumFractionDigits: 0,
      style: "percent",
    }).format(Math.max(0, value) / 100);
  }
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(
    Math.max(0, value),
  );
}

export function activityIntensity(milliseconds: number) {
  if (milliseconds <= 0) return 0;
  if (milliseconds < 15_000) return 1;
  if (milliseconds < 60_000) return 2;
  if (milliseconds < 180_000) return 3;
  return 4;
}

export function relativeActivityIntensity(milliseconds: number, peak: number) {
  if (milliseconds <= 0 || peak <= 0) return 0;
  return Math.min(4, Math.max(1, Math.ceil((milliseconds / peak) * 4)));
}
