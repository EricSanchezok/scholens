"use client";

import { useFormatter, useNow } from "next-intl";
import { useCallback, useSyncExternalStore } from "react";

/**
 * Live wall-clock reference for relative-time labels.
 *
 * The root provider pins `now` at request time so server and client render
 * identically. That reference never advances during a long-lived SPA session,
 * so a freshly created annotation can appear to be in the future. This hook
 * keeps one shared 15-second browser clock for every mounted relative-time
 * label while retaining the provider timestamp for hydration.
 */
const relativeTimeUpdateIntervalMs = 15_000;
const relativeTimeListeners = new Set<() => void>();
let liveNow: Date | undefined;
let relativeTimeInterval: ReturnType<typeof setInterval> | undefined;

function subscribeToRelativeTime(listener: () => void) {
  relativeTimeListeners.add(listener);
  if (relativeTimeListeners.size === 1) {
    relativeTimeInterval = setInterval(() => {
      liveNow = new Date();
      for (const notify of relativeTimeListeners) notify();
    }, relativeTimeUpdateIntervalMs);
  }

  return () => {
    relativeTimeListeners.delete(listener);
    if (relativeTimeListeners.size === 0 && relativeTimeInterval) {
      clearInterval(relativeTimeInterval);
      relativeTimeInterval = undefined;
      liveNow = undefined;
    }
  };
}

export function useRelativeTimeNow() {
  const format = useFormatter();
  const providerNow = useNow();
  const now = useSyncExternalStore(
    subscribeToRelativeTime,
    () => liveNow ?? providerNow,
    () => providerNow,
  );
  return useCallback(
    (value: Date | number | string) =>
      format.relativeTime(new Date(value), now),
    [format, now],
  );
}
