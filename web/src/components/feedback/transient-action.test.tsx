import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useTransientActionFeedback } from "./transient-action";

describe("useTransientActionFeedback", () => {
  afterEach(() => vi.useRealTimers());

  it("reports success and returns to idle after the feedback interval", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useTransientActionFeedback({ duration: 100 }),
    );

    await act(() => result.current.run(async () => undefined));
    expect(result.current.status).toBe("success");

    act(() => vi.advanceTimersByTime(100));
    expect(result.current.status).toBe("idle");
  });

  it("reports failure without swallowing the action error", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useTransientActionFeedback({ duration: 100 }),
    );
    const failure = new Error("Action failed");

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.run(async () => Promise.reject(failure));
      } catch (error) {
        caught = error;
      }
    });
    expect(caught).toBe(failure);
    expect(result.current.status).toBe("error");

    act(() => vi.advanceTimersByTime(100));
    expect(result.current.status).toBe("idle");
  });
});
