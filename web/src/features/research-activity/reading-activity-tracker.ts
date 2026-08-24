export const READING_ACTIVITY_METRIC_VERSION = "active-reading-v1";
export const READING_ACTIVITY_IDLE_MS = 120_000;
export const READING_ACTIVITY_TICK_MS = 5_000;
export const READING_ACTIVITY_FLUSH_MS = 30_000;
export const READING_ACTIVITY_SEGMENT_COUNT = 20;
export const READING_ACTIVITY_SESSION_MAX_MS = 24 * 60 * 60 * 1_000;
export const READING_ACTIVITY_SESSION_ROLLOVER_MS =
  READING_ACTIVITY_SESSION_MAX_MS - 60_000;

const UTC_HOUR_MS = 60 * 60 * 1_000;

export type ReadingViewMode = "pdf" | "reflow";

export type VisibleReadingTarget = {
  pageNumber: number;
  weight: number;
  segmentWeights: number[];
};

export type ReadingActivityPageSnapshot = {
  page_number: number;
  visible_ms: number;
  active_ms: number;
  visit_count: number;
  vertical_segments_ms: number[];
};

export type ReadingActivityHourSnapshot = {
  bucket_start: string;
  visible_ms: number;
  active_ms: number;
};

export type ReadingActivitySnapshot = {
  visible_ms: number;
  active_ms: number;
  hours: ReadingActivityHourSnapshot[];
  pages: ReadingActivityPageSnapshot[];
};

type MutablePageActivity = {
  visibleMs: number;
  activeMs: number;
  visitCount: number;
  verticalSegmentsMs: number[];
};

type PageDwell = { counted: boolean; startedAt: number };
type MutableHourActivity = { activeMs: number; visibleMs: number };

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function intersectRect(left: DOMRect, right: DOMRect) {
  const x1 = Math.max(left.left, right.left);
  const y1 = Math.max(left.top, right.top);
  const x2 = Math.min(left.right, right.right);
  const y2 = Math.min(left.bottom, right.bottom);
  if (x2 <= x1 || y2 <= y1) return undefined;
  return {
    bottom: y2,
    height: y2 - y1,
    left: x1,
    right: x2,
    top: y1,
    width: x2 - x1,
  };
}

function viewportRect(): DOMRect {
  const width = window.innerWidth;
  const height = window.innerHeight;
  return new DOMRect(0, 0, width, height);
}

function segmentWeights(start: number, end: number) {
  const resolvedStart = clamp(start, 0, 1);
  const resolvedEnd = clamp(end, resolvedStart, 1);
  const weights = Array.from(
    { length: READING_ACTIVITY_SEGMENT_COUNT },
    () => 0,
  );
  const total = resolvedEnd - resolvedStart;
  if (total <= 0) return weights;
  for (let index = 0; index < weights.length; index += 1) {
    const segmentStart = index / weights.length;
    const segmentEnd = (index + 1) / weights.length;
    const overlap = Math.max(
      0,
      Math.min(resolvedEnd, segmentEnd) - Math.max(resolvedStart, segmentStart),
    );
    weights[index] = overlap / total;
  }
  return weights;
}

function normalizedSegmentWeights(weights: number[]) {
  const total = weights.reduce((sum, value) => sum + value, 0);
  if (total > 0) return weights.map((value) => value / total);
  return Array.from(
    { length: READING_ACTIVITY_SEGMENT_COUNT },
    () => 1 / READING_ACTIVITY_SEGMENT_COUNT,
  );
}

function mergeTargets(targets: VisibleReadingTarget[]) {
  const byPage = new Map<number, VisibleReadingTarget>();
  for (const target of targets) {
    const existing = byPage.get(target.pageNumber);
    if (!existing) {
      byPage.set(target.pageNumber, {
        ...target,
        segmentWeights: [...target.segmentWeights],
      });
      continue;
    }
    const combinedWeight = existing.weight + target.weight;
    existing.segmentWeights = existing.segmentWeights.map((value, index) => {
      const incoming = target.segmentWeights[index] ?? 0;
      return combinedWeight
        ? (value * existing.weight + incoming * target.weight) / combinedWeight
        : 0;
    });
    existing.weight = combinedWeight;
  }
  return [...byPage.values()].sort(
    (left, right) => left.pageNumber - right.pageNumber,
  );
}

export function collectVisibleReadingTargets(
  root: HTMLElement,
  viewMode: ReadingViewMode,
) {
  const rootRect = intersectRect(root.getBoundingClientRect(), viewportRect());
  if (!rootRect) return [];
  const selector =
    viewMode === "pdf"
      ? "[data-pdf-page-number]"
      : "[data-reflow-block][data-source-page-number]";
  const targets: VisibleReadingTarget[] = [];
  for (const element of root.querySelectorAll<HTMLElement>(selector)) {
    const rect = element.getBoundingClientRect();
    const visible = intersectRect(
      rect,
      new DOMRect(rootRect.left, rootRect.top, rootRect.width, rootRect.height),
    );
    if (!visible) continue;
    const pageNumber = Number(
      viewMode === "pdf"
        ? element.dataset.pdfPageNumber
        : element.dataset.sourcePageNumber,
    );
    if (!Number.isInteger(pageNumber) || pageNumber <= 0) continue;
    const weight = visible.width * visible.height;
    if (weight <= 0) continue;
    if (viewMode === "pdf") {
      targets.push({
        pageNumber,
        segmentWeights: normalizedSegmentWeights(
          segmentWeights(
            (visible.top - rect.top) / Math.max(1, rect.height),
            (visible.bottom - rect.top) / Math.max(1, rect.height),
          ),
        ),
        weight,
      });
      continue;
    }
    const sourceY = Number(element.dataset.sourceY ?? 0);
    const sourceHeight = Number(element.dataset.sourceHeight ?? 1);
    const visibleStart = (visible.top - rect.top) / Math.max(1, rect.height);
    const visibleEnd = (visible.bottom - rect.top) / Math.max(1, rect.height);
    targets.push({
      pageNumber,
      segmentWeights: normalizedSegmentWeights(
        segmentWeights(
          sourceY + sourceHeight * visibleStart,
          sourceY + sourceHeight * visibleEnd,
        ),
      ),
      weight,
    });
  }
  return mergeTargets(targets);
}

function distribute(total: number, weights: number[]) {
  const resolvedTotal = Math.max(0, Math.round(total));
  if (weights.length === 0) return [];
  const positiveWeights = weights.map((weight) =>
    Number.isFinite(weight) && weight > 0 ? weight : 0,
  );
  const positiveTotal = positiveWeights.reduce(
    (sum, weight) => sum + weight,
    0,
  );
  const safeWeights =
    positiveTotal > 0 ? positiveWeights : positiveWeights.map(() => 1);
  const safeTotal = safeWeights.reduce((sum, weight) => sum + weight, 0);
  const quotas = safeWeights.map(
    (weight) => (resolvedTotal * weight) / safeTotal,
  );
  const allocations = quotas.map(Math.floor);
  let remainder =
    resolvedTotal - allocations.reduce((sum, value) => sum + value, 0);
  const remainderOrder = quotas
    .map((quota, index) => ({ fraction: quota - Math.floor(quota), index }))
    .filter(({ index }) => safeWeights[index] !== 0)
    .sort(
      (left, right) =>
        right.fraction - left.fraction || left.index - right.index,
    );
  for (const { index } of remainderOrder) {
    if (remainder === 0) break;
    allocations[index] = (allocations[index] ?? 0) + 1;
    remainder -= 1;
  }
  return allocations;
}

function utcHourStart(timestamp: number) {
  return Math.floor(timestamp / UTC_HOUR_MS) * UTC_HOUR_MS;
}

/**
 * Attributes only the admitted slice, ending at the observed wall clock. A
 * delayed callback therefore contributes at most the metric's five-second
 * cap instead of filling an offline/background gap.
 */
function splitReadingSliceByUtcHour(wallEndedAt: number, elapsedMs: number) {
  const elapsed = Math.round(clamp(elapsedMs, 0, READING_ACTIVITY_TICK_MS));
  if (!Number.isFinite(wallEndedAt) || elapsed === 0) return [];
  const end = Math.round(wallEndedAt);
  let cursor = end - elapsed;
  const slices: Array<{ bucketStart: number; elapsedMs: number }> = [];
  while (cursor < end) {
    const bucketStart = utcHourStart(cursor);
    const sliceEnd = Math.min(end, bucketStart + UTC_HOUR_MS);
    const sliceElapsed = sliceEnd - cursor;
    if (sliceElapsed > 0) {
      slices.push({ bucketStart, elapsedMs: sliceElapsed });
    }
    cursor = sliceEnd;
  }
  return slices;
}

export class ReadingActivityAccumulator {
  private activeMs = 0;
  private visibleMs = 0;
  private readonly hours = new Map<number, MutableHourActivity>();
  private readonly pages = new Map<number, MutablePageActivity>();
  private readonly dwell = new Map<number, PageDwell>();

  record({
    active,
    elapsedMs,
    now,
    targets,
    visible,
    wallNow,
  }: {
    active: boolean;
    elapsedMs: number;
    now: number;
    targets: VisibleReadingTarget[];
    visible: boolean;
    wallNow: number;
  }) {
    const elapsed = Math.round(clamp(elapsedMs, 0, READING_ACTIVITY_TICK_MS));
    const validTargets = targets.filter((target) => target.weight > 0);
    if (!visible || elapsed === 0 || validTargets.length === 0) {
      this.dwell.clear();
      return;
    }

    this.visibleMs += elapsed;
    if (active) this.activeMs += elapsed;
    splitReadingSliceByUtcHour(wallNow, elapsed).forEach(
      ({ bucketStart, elapsedMs: sliceElapsed }) => {
        const hour = this.hours.get(bucketStart) ?? {
          activeMs: 0,
          visibleMs: 0,
        };
        hour.visibleMs += sliceElapsed;
        if (active) hour.activeMs += sliceElapsed;
        this.hours.set(bucketStart, hour);
      },
    );
    const pageWeights = validTargets.map((target) => target.weight);
    const visibleAllocations = distribute(elapsed, pageWeights);
    const activeAllocations = distribute(active ? elapsed : 0, pageWeights);
    const currentlyVisible = new Set(
      validTargets.map((target) => target.pageNumber),
    );

    for (const pageNumber of [...this.dwell.keys()]) {
      if (!currentlyVisible.has(pageNumber)) this.dwell.delete(pageNumber);
    }

    validTargets.forEach((target, index) => {
      const page = this.pages.get(target.pageNumber) ?? {
        activeMs: 0,
        visibleMs: 0,
        visitCount: 0,
        verticalSegmentsMs: Array.from(
          { length: READING_ACTIVITY_SEGMENT_COUNT },
          () => 0,
        ),
      };
      page.visibleMs += visibleAllocations[index] ?? 0;
      const pageActiveMs = activeAllocations[index] ?? 0;
      page.activeMs += pageActiveMs;
      const segmentAllocations = distribute(
        pageActiveMs,
        target.segmentWeights,
      );
      page.verticalSegmentsMs = page.verticalSegmentsMs.map(
        (value, segmentIndex) =>
          value + (segmentAllocations[segmentIndex] ?? 0),
      );

      const dwell = this.dwell.get(target.pageNumber) ?? {
        counted: false,
        startedAt: now - elapsed,
      };
      if (!dwell.counted && now - dwell.startedAt >= 2_000) {
        page.visitCount += 1;
        dwell.counted = true;
      }
      this.dwell.set(target.pageNumber, dwell);
      this.pages.set(target.pageNumber, page);
    });
  }

  snapshot(pageNumbers?: ReadonlySet<number>): ReadingActivitySnapshot {
    return {
      active_ms: this.activeMs,
      hours: [...this.hours.entries()]
        .sort(([left], [right]) => left - right)
        .map(([bucketStart, hour]) => ({
          active_ms: hour.activeMs,
          bucket_start: new Date(bucketStart).toISOString(),
          visible_ms: hour.visibleMs,
        })),
      pages: [...this.pages.entries()]
        .filter(([pageNumber]) => !pageNumbers || pageNumbers.has(pageNumber))
        .sort(([left], [right]) => left - right)
        .map(([pageNumber, page]) => ({
          active_ms: page.activeMs,
          page_number: pageNumber,
          vertical_segments_ms: [...page.verticalSegmentsMs],
          visible_ms: page.visibleMs,
          visit_count: page.visitCount,
        })),
      visible_ms: this.visibleMs,
    };
  }
}

export function readingRootVisible(root: HTMLElement) {
  const rect = root.getBoundingClientRect();
  const visible = intersectRect(rect, viewportRect());
  if (!visible || rect.width <= 0 || rect.height <= 0) return false;
  return (visible.width * visible.height) / (rect.width * rect.height) >= 0.25;
}
