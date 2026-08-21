import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createReaderSelectionPageCoordinator,
  READER_SELECTION_PAGE_ACK_TIMEOUT_MS,
} from "./reader-selection-page-coordinator";

afterEach(() => {
  vi.useRealTimers();
});

describe("createReaderSelectionPageCoordinator", () => {
  it("defers the stale route prop until the pending page is acknowledged", () => {
    const guardChanges: boolean[] = [];
    const reports: number[] = [];
    const settled: Array<[number, boolean]> = [];
    const coordinator = createReaderSelectionPageCoordinator({
      onGuardChange: (guarded) => guardChanges.push(guarded),
      onReportPage: (pageNumber) => reports.push(pageNumber),
      onSettleReport: (pageNumber, acknowledged) =>
        settled.push([pageNumber, acknowledged]),
    });

    coordinator.startGesture(2);
    coordinator.finishGesture(3);

    expect(reports).toEqual([3]);
    expect(coordinator.routePageChanged(2)).toBe("defer");
    expect(coordinator.isGuarded()).toBe(true);
    expect(settled).toEqual([]);

    expect(coordinator.routePageChanged(3)).toBe("acknowledged");
    expect(coordinator.isGuarded()).toBe(false);
    expect(settled).toEqual([[3, true]]);
    expect(guardChanges).toEqual([true, false]);
  });

  it("cancels the pending report and allows a different external page", () => {
    const guardChanges: boolean[] = [];
    const settled: Array<[number, boolean]> = [];
    const coordinator = createReaderSelectionPageCoordinator({
      onGuardChange: (guarded) => guardChanges.push(guarded),
      onReportPage: vi.fn(),
      onSettleReport: (pageNumber, acknowledged) =>
        settled.push([pageNumber, acknowledged]),
    });

    coordinator.startGesture(2);
    coordinator.finishGesture(3);

    expect(coordinator.routePageChanged(5)).toBe("continue");
    expect(coordinator.isGuarded()).toBe(false);
    expect(settled).toEqual([[3, false]]);
    expect(guardChanges).toEqual([true, false]);
    expect(coordinator.routePageChanged(5)).toBe("continue");
  });

  it("releases and discards an unacknowledged report after the bounded timeout", () => {
    vi.useFakeTimers();
    const guardChanges: boolean[] = [];
    const settled: Array<[number, boolean]> = [];
    const coordinator = createReaderSelectionPageCoordinator({
      onGuardChange: (guarded) => guardChanges.push(guarded),
      onReportPage: vi.fn(),
      onSettleReport: (pageNumber, acknowledged) =>
        settled.push([pageNumber, acknowledged]),
    });

    coordinator.startGesture(2);
    coordinator.finishGesture(3);
    vi.advanceTimersByTime(READER_SELECTION_PAGE_ACK_TIMEOUT_MS);

    expect(settled).toEqual([[3, false]]);
    expect(coordinator.isGuarded()).toBe(false);
    expect(coordinator.routePageChanged(2)).toBe("continue");
    expect(guardChanges).toEqual([true, false]);
  });

  it("releases immediately when the gesture has no pending page", () => {
    const guardChanges: boolean[] = [];
    const coordinator = createReaderSelectionPageCoordinator({
      onGuardChange: (guarded) => guardChanges.push(guarded),
      onReportPage: vi.fn(),
      onSettleReport: vi.fn(),
    });

    coordinator.startGesture(2);
    coordinator.finishGesture(undefined);

    expect(coordinator.isGuarded()).toBe(false);
    expect(guardChanges).toEqual([true, false]);
  });

  it("cancels pending acknowledgement work when disposed", () => {
    vi.useFakeTimers();
    const settle = vi.fn();
    const guard = vi.fn();
    const coordinator = createReaderSelectionPageCoordinator({
      onGuardChange: guard,
      onReportPage: vi.fn(),
      onSettleReport: settle,
    });

    coordinator.startGesture(2);
    coordinator.finishGesture(3);
    coordinator.dispose();
    vi.runAllTimers();

    expect(settle).toHaveBeenCalledOnce();
    expect(settle).toHaveBeenCalledWith(3, false);
    expect(guard).toHaveBeenCalledTimes(1);
  });
});
