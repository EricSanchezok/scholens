import { describe, expect, it } from "vitest";

import {
  conversationBottomGap,
  conversationScrollTopForMotion,
  nextConversationFollowingState,
  nextConversationScrollTop,
} from "./use-conversation-auto-scroll";

describe("conversationBottomGap", () => {
  it("measures the remaining scrollable distance", () => {
    expect(
      conversationBottomGap({
        clientHeight: 500,
        scrollHeight: 1_400,
        scrollTop: 640,
      }),
    ).toBe(260);
  });

  it("never returns a negative gap for rounded browser geometry", () => {
    expect(
      conversationBottomGap({
        clientHeight: 500,
        scrollHeight: 999.5,
        scrollTop: 500,
      }),
    ).toBe(0);
  });
});

describe("nextConversationFollowingState", () => {
  it("keeps programmatic animation scroll events from cancelling follow", () => {
    expect(
      nextConversationFollowingState({
        current: true,
        gap: 300,
        movingUp: false,
        programmatic: true,
      }),
    ).toBe(true);
  });

  it("honors an upward user scroll even near the bottom", () => {
    expect(
      nextConversationFollowingState({
        current: true,
        gap: 40,
        movingUp: true,
        programmatic: false,
      }),
    ).toBe(false);
  });

  it("re-engages when the user returns toward the bottom", () => {
    expect(
      nextConversationFollowingState({
        current: false,
        gap: 40,
        movingUp: false,
        programmatic: false,
      }),
    ).toBe(true);
  });
});

describe("nextConversationScrollTop", () => {
  it("moves toward a changing target without jumping past it", () => {
    const first = nextConversationScrollTop({
      current: 100,
      elapsedMs: 16,
      target: 300,
    });
    const retargeted = nextConversationScrollTop({
      current: first,
      elapsedMs: 16,
      target: 340,
    });

    expect(first).toBeGreaterThan(100);
    expect(first).toBeLessThan(300);
    expect(retargeted).toBeGreaterThan(first);
    expect(retargeted).toBeLessThan(340);
  });

  it("snaps the final sub-pixel remainder to the target", () => {
    expect(
      nextConversationScrollTop({
        current: 299.7,
        elapsedMs: 16,
        target: 300,
      }),
    ).toBe(300);
  });

  it("caps a delayed frame so a resumed tab does not leap", () => {
    expect(
      nextConversationScrollTop({
        current: 0,
        elapsedMs: 1_000,
        target: 100,
      }),
    ).toBeCloseTo(
      nextConversationScrollTop({
        current: 0,
        elapsedMs: 32,
        target: 100,
      }),
    );
  });
});

describe("conversationScrollTopForMotion", () => {
  it("moves directly to the target for the resolved reduced policy", () => {
    expect(
      conversationScrollTopForMotion({
        current: 100,
        elapsedMs: 16,
        resolvedMotion: "reduced",
        target: 800,
      }),
    ).toBe(800);
  });

  it("keeps retargetable interpolation for the resolved full policy", () => {
    const next = conversationScrollTopForMotion({
      current: 100,
      elapsedMs: 16,
      resolvedMotion: "full",
      target: 800,
    });
    expect(next).toBeGreaterThan(100);
    expect(next).toBeLessThan(800);
  });
});
