"use client";

import { useFormatter, useNow } from "next-intl";

/**
 * Live wall-clock reference for relative-time labels.
 *
 * The root provider pins `now` at request time so server and client render
 * identically. That reference never advances during a long-lived SPA session,
 * so a freshly created annotation can appear to be in the future. This hook
 * keeps one shared 15-second tick per consumer surface and formats relative
 * time against it, following the documented next-intl `useNow` pattern.
 */
const relativeTimeUpdateIntervalMs = 15_000;

export function useRelativeTimeNow() {
  const format = useFormatter();
  const now = useNow({ updateInterval: relativeTimeUpdateIntervalMs });
  return (value: Date | number | string) =>
    format.relativeTime(new Date(value), now);
}
