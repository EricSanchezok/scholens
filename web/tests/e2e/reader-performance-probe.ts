import { expect, type Page } from "@playwright/test";

type MetricsWindow = Window & {
  readerProbe: {
    shifts: { at: number; value: number; sources: unknown[] }[];
    interactions: Record<number, number>;
  };
};

/** Opt-in release evidence on a production build, separate from field RUM. */
export async function attachReaderPerformanceProbe(page: Page) {
  await page.addInitScript(() => {
    const target = window as unknown as MetricsWindow;
    target.readerProbe = { shifts: [], interactions: {} };
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const shift = entry as PerformanceEntry & {
          hadRecentInput: boolean;
          value: number;
          sources?: {
            node?: Element;
            previousRect: DOMRectReadOnly;
            currentRect: DOMRectReadOnly;
          }[];
        };
        if (!shift.hadRecentInput) {
          target.readerProbe.shifts.push({
            at: shift.startTime,
            value: shift.value,
            sources: (shift.sources ?? []).map((source) => ({
              node: source.node?.outerHTML?.slice(0, 500),
              previous: source.previousRect.toJSON(),
              current: source.currentRect.toJSON(),
            })),
          });
        }
      }
    }).observe({ type: "layout-shift", buffered: true });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const event = entry as PerformanceEventTiming & {
          interactionId?: number;
        };
        if (event.interactionId) {
          target.readerProbe.interactions[event.interactionId] = Math.max(
            target.readerProbe.interactions[event.interactionId] ?? 0,
            event.duration,
          );
        }
      }
    }).observe({
      type: "event",
      buffered: true,
      durationThreshold: 16,
    } as PerformanceObserverInit & { durationThreshold: number });
  });
  const cdp = await page.context().newCDPSession(page);
  const cycles: { heapBytes: number; nodes: number; documents: number }[] = [];
  return {
    async checkpoint() {
      await cdp.send("HeapProfiler.collectGarbage");
      const heap = await cdp.send("Runtime.getHeapUsage");
      const dom = await cdp.send("Memory.getDOMCounters");
      cycles.push({
        heapBytes: heap.usedSize,
        nodes: dom.nodes,
        documents: dom.documents,
      });
    },
    async finish() {
      const result = await page.evaluate(() => {
        const { shifts, interactions } = (window as unknown as MetricsWindow)
          .readerProbe;
        let cls = 0,
          sum = 0,
          start = 0,
          previous = 0;
        for (const shift of shifts) {
          if (shift.at - previous > 1000 || shift.at - start > 5000) {
            start = shift.at;
            sum = 0;
          }
          sum += shift.value;
          cls = Math.max(cls, sum);
          previous = shift.at;
        }
        const durations = Object.values(interactions).sort((a, b) => b - a);
        return {
          cls,
          shifts,
          slowInteractionCount: durations.length,
          longestInteractionMs: durations[0] ?? 0,
        };
      });
      await cdp.detach();
      expect(cycles).toHaveLength(3);
      // The first traversal warms fonts, the worker and the bounded text cache.
      // Compare equivalent post-GC positions after two further full traversals.
      expect(cycles[2]!.heapBytes - cycles[1]!.heapBytes).toBeLessThan(
        8 * 1024 * 1024,
      );
      expect(cycles[2]!.nodes - cycles[1]!.nodes).toBeLessThan(2000);
      expect.soft(result.cls).toBeLessThanOrEqual(0.1);
      expect.soft(result.longestInteractionMs).toBeLessThanOrEqual(200);
      return {
        ...result,
        cycles,
        scope: "controlled Chromium desktop fixture; not population RUM",
      };
    },
  };
}
