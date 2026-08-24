import { describe, expect, it } from "vitest";

import {
  collectVisibleReadingTargets,
  READING_ACTIVITY_SEGMENT_COUNT,
  ReadingActivityAccumulator,
} from "./reading-activity-tracker";

const target = {
  pageNumber: 3,
  segmentWeights: Array.from(
    { length: READING_ACTIVITY_SEGMENT_COUNT },
    (_, index) => (index === 4 ? 1 : 0),
  ),
  weight: 1,
};

describe("ReadingActivityAccumulator", () => {
  it("keeps visible and active time separate", () => {
    const activity = new ReadingActivityAccumulator();
    activity.record({
      active: true,
      elapsedMs: 5_000,
      now: 5_000,
      targets: [target],
      visible: true,
      wallNow: Date.parse("2026-08-24T12:00:05Z"),
    });
    activity.record({
      active: false,
      elapsedMs: 5_000,
      now: 10_000,
      targets: [target],
      visible: true,
      wallNow: Date.parse("2026-08-24T12:00:10Z"),
    });

    const snapshot = activity.snapshot();
    expect(snapshot.visible_ms).toBe(10_000);
    expect(snapshot.active_ms).toBe(5_000);
    expect(snapshot.pages[0]).toMatchObject({
      active_ms: 5_000,
      page_number: 3,
      visible_ms: 10_000,
      visit_count: 1,
    });
    expect(snapshot.pages[0]?.vertical_segments_ms[4]).toBe(5_000);
    expect(snapshot.hours).toEqual([
      {
        active_ms: 5_000,
        bucket_start: "2026-08-24T12:00:00.000Z",
        visible_ms: 10_000,
      },
    ]);
  });

  it("does not double count a slice shared by two pages", () => {
    const activity = new ReadingActivityAccumulator();
    activity.record({
      active: true,
      elapsedMs: 5_000,
      now: 5_000,
      targets: [target, { ...target, pageNumber: 4, weight: 3 }],
      visible: true,
      wallNow: Date.parse("2026-08-24T12:00:05Z"),
    });

    const snapshot = activity.snapshot();
    expect(snapshot.pages.reduce((sum, page) => sum + page.active_ms, 0)).toBe(
      5_000,
    );
    expect(snapshot.pages[0]?.active_ms).toBe(1_250);
    expect(snapshot.pages[1]?.active_ms).toBe(3_750);
    expect(activity.snapshot(new Set([3])).hours).toEqual(
      activity.snapshot(new Set([4])).hours,
    );
  });

  it("preserves exact totals for adversarial fractional weights", () => {
    for (let seed = 1; seed <= 50; seed += 1) {
      const activity = new ReadingActivityAccumulator();
      const targets = Array.from({ length: 7 }, (_, index) => ({
        ...target,
        pageNumber: index + 1,
        segmentWeights: Array.from({ length: 20 }, (_, segment) =>
          (seed * (index + 3) * (segment + 5)) % 13 === 0
            ? 0
            : ((seed + index + segment) % 11) / 10,
        ),
        weight: index === 0 ? 1 : ((seed * (index + 1)) % 10) / 10,
      })).filter(({ weight }) => weight > 0);
      activity.record({
        active: true,
        elapsedMs: 5,
        now: 5,
        targets,
        visible: true,
        wallNow: Date.parse("2026-08-24T12:00:00.005Z"),
      });

      const snapshot = activity.snapshot();
      expect(
        snapshot.pages.reduce((sum, page) => sum + page.active_ms, 0),
      ).toBe(5);
      snapshot.pages.forEach((page) => {
        expect(
          page.vertical_segments_ms.reduce((sum, value) => sum + value, 0),
        ).toBe(page.active_ms);
      });
    }
  });

  it("never assigns remainder to a zero-weight trailing segment", () => {
    const activity = new ReadingActivityAccumulator();
    activity.record({
      active: true,
      elapsedMs: 5,
      now: 5,
      targets: [target],
      visible: true,
      wallNow: Date.parse("2026-08-24T12:00:00.005Z"),
    });

    expect(activity.snapshot().pages[0]?.vertical_segments_ms).toEqual([
      0,
      0,
      0,
      0,
      5,
      ...Array.from({ length: 15 }, () => 0),
    ]);
  });

  it("starts a new visit only after the page leaves and returns", () => {
    const activity = new ReadingActivityAccumulator();
    activity.record({
      active: true,
      elapsedMs: 2_500,
      now: 2_500,
      targets: [target],
      visible: true,
      wallNow: Date.parse("2026-08-24T12:00:02.500Z"),
    });
    activity.record({
      active: false,
      elapsedMs: 1_000,
      now: 3_500,
      targets: [],
      visible: false,
      wallNow: Date.parse("2026-08-24T12:00:03.500Z"),
    });
    activity.record({
      active: true,
      elapsedMs: 2_500,
      now: 6_000,
      targets: [target],
      visible: true,
      wallNow: Date.parse("2026-08-24T12:00:06Z"),
    });

    expect(activity.snapshot().pages[0]?.visit_count).toBe(2);
  });

  it("caps a delayed browser tick to one five-second slice", () => {
    const activity = new ReadingActivityAccumulator();
    activity.record({
      active: true,
      elapsedMs: 21_000,
      now: 21_000,
      targets: [target],
      visible: true,
      wallNow: Date.parse("2026-08-24T14:00:02Z"),
    });

    expect(activity.snapshot().active_ms).toBe(5_000);
    expect(
      activity.snapshot().hours.reduce((sum, hour) => sum + hour.active_ms, 0),
    ).toBe(5_000);
    expect(activity.snapshot().hours).toEqual([
      {
        active_ms: 3_000,
        bucket_start: "2026-08-24T13:00:00.000Z",
        visible_ms: 3_000,
      },
      {
        active_ms: 2_000,
        bucket_start: "2026-08-24T14:00:00.000Z",
        visible_ms: 2_000,
      },
    ]);
  });

  it("does not create hour evidence while hidden", () => {
    const activity = new ReadingActivityAccumulator();
    activity.record({
      active: false,
      elapsedMs: 5_000,
      now: 5_000,
      targets: [target],
      visible: false,
      wallNow: Date.parse("2026-08-24T12:00:05Z"),
    });

    expect(activity.snapshot()).toMatchObject({
      active_ms: 0,
      hours: [],
      visible_ms: 0,
    });
  });

  it("keeps a hidden two-hour midnight gap out of cumulative buckets", () => {
    const activity = new ReadingActivityAccumulator();
    activity.record({
      active: true,
      elapsedMs: 2_000,
      now: 2_000,
      targets: [target],
      visible: true,
      wallNow: Date.parse("2026-08-24T23:59:58Z"),
    });
    activity.record({
      active: false,
      elapsedMs: 2 * 60 * 60 * 1_000,
      now: 2 * 60 * 60 * 1_000 + 2_000,
      targets: [target],
      visible: false,
      wallNow: Date.parse("2026-08-25T01:59:58Z"),
    });
    activity.record({
      active: true,
      elapsedMs: 5_000,
      now: 2 * 60 * 60 * 1_000 + 7_000,
      targets: [target],
      visible: true,
      wallNow: Date.parse("2026-08-25T02:00:03Z"),
    });

    expect(activity.snapshot().hours).toEqual([
      {
        active_ms: 2_000,
        bucket_start: "2026-08-24T23:00:00.000Z",
        visible_ms: 2_000,
      },
      {
        active_ms: 2_000,
        bucket_start: "2026-08-25T01:00:00.000Z",
        visible_ms: 2_000,
      },
      {
        active_ms: 3_000,
        bucket_start: "2026-08-25T02:00:00.000Z",
        visible_ms: 3_000,
      },
    ]);
  });

  it("distributes an unmapped segment uniformly instead of inventing a bottom hotspot", () => {
    const activity = new ReadingActivityAccumulator();
    activity.record({
      active: true,
      elapsedMs: 5_000,
      now: 5_000,
      targets: [
        { ...target, segmentWeights: Array.from({ length: 20 }, () => 0) },
      ],
      visible: true,
      wallNow: Date.parse("2026-08-24T12:00:05Z"),
    });

    const segments = activity.snapshot().pages[0]?.vertical_segments_ms ?? [];
    expect(segments.reduce((sum, value) => sum + value, 0)).toBe(5_000);
    expect(Math.max(...segments) - Math.min(...segments)).toBeLessThanOrEqual(
      1,
    );
  });

  it("normalizes malformed reflow source coordinates before collection", () => {
    const root = document.createElement("div");
    const block = document.createElement("p");
    block.dataset.reflowBlock = "block-1";
    block.dataset.sourcePageNumber = "2";
    block.dataset.sourceY = "not-a-number";
    block.dataset.sourceHeight = "not-a-number";
    root.append(block);
    root.getBoundingClientRect = () => new DOMRect(0, 0, 800, 600);
    block.getBoundingClientRect = () => new DOMRect(40, 80, 720, 120);

    const [collected] = collectVisibleReadingTargets(root, "reflow");
    expect(collected?.pageNumber).toBe(2);
    expect(collected?.segmentWeights).toHaveLength(
      READING_ACTIVITY_SEGMENT_COUNT,
    );
    expect(
      collected?.segmentWeights.reduce((sum, weight) => sum + weight, 0),
    ).toBeCloseTo(1);
    expect(collected?.segmentWeights.every((weight) => weight > 0)).toBe(true);
  });
});
