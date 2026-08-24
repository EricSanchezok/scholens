import { describe, expect, it, vi } from "vitest";

import { createConversationPerformanceTracker } from "./conversation-performance";

describe("createConversationPerformanceTracker", () => {
  it("reports one content-free milestone per stage and the longest stall", () => {
    let timestamp = 100;
    const report = vi.fn();
    const tracker = createConversationPerformanceTracker(
      () => timestamp,
      report,
    );

    timestamp = 112;
    tracker.markFeedback();
    tracker.markFeedback();
    timestamp = 150;
    tracker.markAccepted("direct");
    timestamp = 180;
    tracker.markEvent();
    timestamp = 260;
    tracker.markEvent();
    tracker.markContentVisible();
    tracker.markContentVisible();
    timestamp = 300;
    tracker.markReady();
    tracker.markReady();
    timestamp = 340;
    tracker.markTerminal();
    tracker.markTerminal();

    expect(report.mock.calls).toEqual([
      ["conversation_feedback", 12, undefined],
      ["conversation_accepted", 50, "direct"],
      ["conversation_first_event", 80, "direct"],
      ["conversation_first_content", 160, "direct"],
      ["conversation_ready", 200, "direct"],
      ["conversation_max_stall", 80, "direct"],
    ]);
  });

  it("never reports a negative duration when a test clock moves backwards", () => {
    let timestamp = 100;
    const report = vi.fn();
    const tracker = createConversationPerformanceTracker(
      () => timestamp,
      report,
    );

    timestamp = 90;
    tracker.markFeedback();
    tracker.markReady();
    tracker.markTerminal();

    expect(report.mock.calls).toEqual([
      ["conversation_feedback", 0, undefined],
      ["conversation_ready", 0, undefined],
      ["conversation_max_stall", 0, undefined],
    ]);
  });
});
