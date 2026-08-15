type DateOnlyFormatOptions = {
  day: "numeric";
  month: "short";
  timeZone: "UTC";
  year: "numeric";
};

export type DateTimeFormatter = (
  value: Date | number,
  options?: DateOnlyFormatOptions,
) => string;

export type NumberFormatter = (
  value: number,
  options?: { maximumFractionDigits: number },
) => string;

function parseDateOnlyUtc(value: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) throw new Error("Invalid date-only value");

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    throw new Error("Invalid date-only value");
  }

  return date;
}

export function addDaysToDateOnly(value: string, days: number): string {
  if (!Number.isInteger(days))
    throw new Error("Date-only offset must be whole days");
  const date = parseDateOnlyUtc(value);
  date.setUTCDate(date.getUTCDate() + days);
  return [
    String(date.getUTCFullYear()).padStart(4, "0"),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

export function formatDateOnly(
  value: string,
  format: DateTimeFormatter,
): string {
  return format(parseDateOnlyUtc(value), {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  });
}

export function formatStorageKilobytes(
  valueKb: number,
  format: NumberFormatter,
): string {
  const absolute = Math.abs(valueKb);
  const [value, unit] =
    absolute >= 1024 * 1024
      ? [valueKb / (1024 * 1024), "GiB"]
      : absolute >= 1024
        ? [valueKb / 1024, "MiB"]
        : [valueKb, "KiB"];

  return `${format(value, {
    maximumFractionDigits: value < 10 && !Number.isInteger(value) ? 1 : 0,
  })} ${unit}`;
}
