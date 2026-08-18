import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  readShellVisualViewport,
  useShellVisualViewport,
} from "./use-shell-visual-viewport";

const originalVisualViewport = Object.getOwnPropertyDescriptor(
  window,
  "visualViewport",
);

afterEach(() => {
  vi.restoreAllMocks();
  if (originalVisualViewport) {
    Object.defineProperty(window, "visualViewport", originalVisualViewport);
  } else {
    Reflect.deleteProperty(window, "visualViewport");
  }
});

describe("readShellVisualViewport", () => {
  it("uses the visual viewport metrics when available", () => {
    expect(
      readShellVisualViewport({ height: 640, offsetTop: 24 }, 844),
    ).toEqual({ height: 640, offsetTop: 24 });
  });

  it("falls back to the layout viewport height", () => {
    expect(readShellVisualViewport(null, 812)).toEqual({
      height: 812,
      offsetTop: 0,
    });
  });

  it("tracks visual viewport resize events while enabled", () => {
    const listeners = new Set<EventListener>();
    const visualViewport = {
      height: 640,
      offsetTop: 24,
      addEventListener: vi.fn((_type: string, listener: EventListener) => {
        listeners.add(listener);
      }),
      removeEventListener: vi.fn((_type: string, listener: EventListener) => {
        listeners.delete(listener);
      }),
    };
    Object.defineProperty(window, "visualViewport", {
      configurable: true,
      value: visualViewport,
    });

    const { result, unmount } = renderHook(() => useShellVisualViewport(true));
    expect(result.current).toEqual({ height: 640, offsetTop: 24 });

    visualViewport.height = 600;
    visualViewport.offsetTop = 40;
    act(() => listeners.forEach((listener) => listener(new Event("resize"))));
    expect(result.current).toEqual({ height: 600, offsetTop: 40 });

    unmount();
    expect(listeners.size).toBe(0);
  });

  it("does not subscribe when desktop layout disables tracking", () => {
    const addEventListener = vi.fn();
    Object.defineProperty(window, "visualViewport", {
      configurable: true,
      value: { height: 640, offsetTop: 24, addEventListener },
    });

    const { result } = renderHook(() => useShellVisualViewport(false));

    expect(result.current).toBeNull();
    expect(addEventListener).not.toHaveBeenCalled();
  });
});
