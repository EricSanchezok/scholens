"use client";

import * as React from "react";

import { ApiError } from "@/lib/api";
import {
  collectVisibleReadingTargets,
  READING_ACTIVITY_FLUSH_MS,
  READING_ACTIVITY_IDLE_MS,
  READING_ACTIVITY_METRIC_VERSION,
  READING_ACTIVITY_SESSION_MAX_MS,
  READING_ACTIVITY_SESSION_ROLLOVER_MS,
  READING_ACTIVITY_TICK_MS,
  ReadingActivityAccumulator,
  readingRootVisible,
  type ReadingActivitySnapshot,
  type ReadingViewMode,
} from "./reading-activity-tracker";

export type ReadingSessionStarter = (input: {
  documentId: string;
  keepalive?: boolean;
  metricDefinitionVersion: string;
  projectId?: string;
  sessionId: string;
  startedAt: string;
  timeZone: string;
  viewMode: ReadingViewMode;
}) => Promise<{ revision: number }>;

export type ReadingSessionUpdater = (input: {
  endedAt?: string;
  keepalive?: boolean;
  lastSeenAt: string;
  revision: number;
  sessionId: string;
  snapshot: ReadingActivitySnapshot;
}) => Promise<{ revision: number }>;

const terminalSessionErrorCodes = new Set([
  "reading_session_ended",
  "reading_session_not_found",
  "reading_session_revision_conflict",
]);

function terminalSessionDisposition(error: unknown) {
  if (!(error instanceof ApiError)) return undefined;
  if (error.code && terminalSessionErrorCodes.has(error.code)) return "restart";
  if (error.status >= 400 && error.status < 500 && error.status !== 429) {
    return "stop";
  }
  return undefined;
}

export function useReadingActivityTracker({
  contributionKey,
  documentId,
  enabled,
  projectId,
  rootRef,
  startSession,
  updateSession,
  viewMode,
}: {
  contributionKey: boolean;
  documentId: string;
  enabled: boolean;
  projectId?: string;
  rootRef: React.RefObject<HTMLDivElement | null>;
  startSession: ReadingSessionStarter;
  updateSession: ReadingSessionUpdater;
  viewMode: ReadingViewMode;
}) {
  const [activeMs, setActiveMs] = React.useState(0);
  const [sessionEpoch, setSessionEpoch] = React.useState(0);
  const sessionContributionKey = projectId ? contributionKey : false;

  React.useEffect(() => {
    if (!enabled) return;
    const accumulator = new ReadingActivityAccumulator();
    const sessionId = crypto.randomUUID();
    const startedAtWall = Date.now();
    const startedAt = new Date(startedAtWall).toISOString();
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    let lastInteractionAt = performance.now();
    let lastTickAt = performance.now();
    let lastFlushAt = performance.now();
    let serverRevision = 0;
    let started = false;
    let sessionEnded = false;
    let lifecyclePaused = false;
    let disposed = false;
    let networkPending = false;
    let flushRequested = false;
    let endRequested = false;
    let restartAfterEnd = false;
    let keepaliveRequested = false;
    let pageVersion = 0;
    let lastSentActiveMs = 0;
    let lastSentVisibleMs = 0;
    const dirtyPages = new Map<number, number>();
    let pendingUpdate:
      | {
          endsSession: boolean;
          input: Parameters<ReadingSessionUpdater>[0];
          pageVersions: Array<[number, number]>;
        }
      | undefined;

    const retireSession = (disposition: "restart" | "stop") => {
      pendingUpdate = undefined;
      dirtyPages.clear();
      sessionEnded = true;
      endRequested = false;
      keepaliveRequested = false;
      flushRequested = false;
      if (disposition === "restart" && !disposed) {
        setActiveMs(0);
        setSessionEpoch((epoch) => epoch + 1);
      }
    };

    const markInteraction = () => {
      lastInteractionAt = performance.now();
    };

    const markReaderInteraction = (event: Event) => {
      const root = rootRef.current;
      const target = event.target;
      if (root && target instanceof Node && root.contains(target)) {
        markInteraction();
      }
    };

    async function ensureStarted(keepalive: boolean) {
      if (started) return true;
      try {
        const response = await startSession({
          documentId,
          keepalive,
          metricDefinitionVersion: READING_ACTIVITY_METRIC_VERSION,
          projectId,
          sessionId,
          startedAt,
          timeZone,
          viewMode,
        });
        serverRevision = response.revision;
        started = true;
        return true;
      } catch (error) {
        if (terminalSessionDisposition(error)) retireSession("stop");
        return false;
      }
    }

    async function flush(ended = false, keepalive = false) {
      if (sessionEnded) return;
      flushRequested = true;
      endRequested ||= ended;
      keepaliveRequested ||= keepalive;
      if (networkPending) return;
      networkPending = true;
      try {
        while (flushRequested && !sessionEnded) {
          flushRequested = false;
          if (!pendingUpdate) {
            const shouldEnd = endRequested;
            const shouldKeepalive = keepaliveRequested;
            const now = new Date().toISOString();
            const pendingPages = [...dirtyPages.entries()].slice(0, 100);
            const pendingPageNumbers = new Set(
              pendingPages.map(([pageNumber]) => pageNumber),
            );
            const snapshot = accumulator.snapshot(pendingPageNumbers);
            const finalChunk = dirtyPages.size <= pendingPages.length;
            if (
              pendingPages.length === 0 &&
              snapshot.active_ms === lastSentActiveMs &&
              snapshot.visible_ms === lastSentVisibleMs &&
              !shouldEnd
            ) {
              if (!endRequested) keepaliveRequested = false;
              break;
            }
            if (
              !started &&
              snapshot.active_ms === 0 &&
              snapshot.visible_ms === 0 &&
              pendingPages.length === 0
            ) {
              break;
            }
            if (!(await ensureStarted(shouldKeepalive))) break;
            pendingUpdate = {
              endsSession: shouldEnd && finalChunk,
              input: {
                endedAt: shouldEnd && finalChunk ? now : undefined,
                keepalive: shouldKeepalive,
                lastSeenAt: now,
                revision: serverRevision + 1,
                sessionId,
                snapshot,
              },
              pageVersions: pendingPages,
            };
          }
          const frozenUpdate = pendingUpdate;
          try {
            const response = await updateSession(frozenUpdate.input);
            serverRevision = response.revision;
            lastSentActiveMs = frozenUpdate.input.snapshot.active_ms;
            lastSentVisibleMs = frozenUpdate.input.snapshot.visible_ms;
            frozenUpdate.pageVersions.forEach(([pageNumber, version]) => {
              if (dirtyPages.get(pageNumber) === version) {
                dirtyPages.delete(pageNumber);
              }
            });
            pendingUpdate = undefined;
            if (frozenUpdate.endsSession) {
              sessionEnded = true;
              endRequested = false;
              keepaliveRequested = false;
              if (restartAfterEnd && !disposed) {
                setActiveMs(0);
                setSessionEpoch((epoch) => epoch + 1);
              }
            } else if (dirtyPages.size > 0) {
              flushRequested = true;
            } else if (!endRequested) {
              keepaliveRequested = false;
            }
          } catch (error) {
            const disposition = terminalSessionDisposition(error);
            if (disposition) {
              retireSession(disposition);
            } else {
              flushRequested = !disposed;
            }
            break;
          }
        }
      } finally {
        networkPending = false;
      }
    }

    function tick(allowInitialFlush = true, updateUi = true) {
      if (lifecyclePaused || sessionEnded) return;
      const now = performance.now();
      const wallNow = Date.now();
      const elapsedMs = now - lastTickAt;
      lastTickAt = now;
      const sessionAge = wallNow - startedAtWall;
      if (allowInitialFlush && sessionAge >= READING_ACTIVITY_SESSION_MAX_MS) {
        pendingUpdate = undefined;
        dirtyPages.clear();
        sessionEnded = true;
        setActiveMs(0);
        setSessionEpoch((epoch) => epoch + 1);
        return;
      }
      if (
        allowInitialFlush &&
        sessionAge >= READING_ACTIVITY_SESSION_ROLLOVER_MS
      ) {
        if (started) {
          restartAfterEnd = true;
          void flush(true);
        } else {
          sessionEnded = true;
          setActiveMs(0);
          setSessionEpoch((epoch) => epoch + 1);
        }
        return;
      }
      const root = rootRef.current;
      const visible = Boolean(
        root &&
        document.visibilityState === "visible" &&
        document.hasFocus() &&
        readingRootVisible(root),
      );
      const active =
        visible && now - lastInteractionAt <= READING_ACTIVITY_IDLE_MS;
      const targets = root ? collectVisibleReadingTargets(root, viewMode) : [];
      accumulator.record({
        active,
        elapsedMs,
        now,
        targets,
        visible,
        wallNow,
      });
      const admitted = visible && targets.length > 0;
      if (admitted) {
        targets.forEach(({ pageNumber }) => {
          pageVersion += 1;
          dirtyPages.set(pageNumber, pageVersion);
        });
      }
      const snapshot = accumulator.snapshot();
      if (updateUi) setActiveMs(snapshot.active_ms);
      if (
        allowInitialFlush &&
        (!started || pendingUpdate) &&
        (snapshot.visible_ms > 0 || snapshot.active_ms > 0)
      ) {
        void flush();
      }
      if (now - lastFlushAt >= READING_ACTIVITY_FLUSH_MS) {
        lastFlushAt = now;
        void flush();
      }
    }

    const activityEvents = [
      "keydown",
      "pointerdown",
      "scroll",
      "touchstart",
      "wheel",
    ] as const;
    activityEvents.forEach((event) =>
      document.addEventListener(event, markReaderInteraction, {
        capture: true,
        passive: true,
      }),
    );
    let interval: number | undefined;
    const stopTicker = () => {
      if (interval === undefined) return;
      window.clearInterval(interval);
      interval = undefined;
    };
    const startTicker = () => {
      if (interval !== undefined || sessionEnded) return;
      lastTickAt = performance.now();
      interval = window.setInterval(tick, READING_ACTIVITY_TICK_MS);
    };
    startTicker();
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") void flush(false, true);
      else {
        lastTickAt = performance.now();
        markInteraction();
      }
    };
    const handlePageHide = (event: PageTransitionEvent) => {
      tick(false, false);
      lifecyclePaused = true;
      stopTicker();
      void flush(!event.persisted, true);
    };
    const handlePageShow = (event: PageTransitionEvent) => {
      if (!event.persisted || sessionEnded) return;
      lifecyclePaused = false;
      lastInteractionAt = performance.now();
      lastTickAt = performance.now();
      lastFlushAt = performance.now();
      startTicker();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", markInteraction);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", handlePageShow);

    return () => {
      tick(false, false);
      disposed = true;
      lifecyclePaused = true;
      stopTicker();
      activityEvents.forEach((event) =>
        document.removeEventListener(event, markReaderInteraction, {
          capture: true,
        }),
      );
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", markInteraction);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", handlePageShow);
      void flush(true, true);
    };
  }, [
    documentId,
    enabled,
    projectId,
    rootRef,
    sessionEpoch,
    startSession,
    sessionContributionKey,
    updateSession,
    viewMode,
  ]);

  return { activeMs };
}
