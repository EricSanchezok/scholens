import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { readVisualViewport, useVisualViewport } from "./use-visual-viewport";

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

describe("readVisualViewport", () => {
  it("uses the visual viewport metrics when available", () => {
    expect(readVisualViewport({ height: 640, offsetTop: 24 }, 844)).toEqual({
      height: 640,
      offsetTop: 24,
    });
  });

  it("falls back to the layout viewport height", () => {
    expect(readVisualViewport(null, 812)).toEqual({
      height: 812,
      offsetTop: 0,
    });
  });
});

describe("useVisualViewport", () => {
  it("tracks resize and scroll events while enabled", () => {
    const listeners = new Map<string, Set<EventListener>>();
    const visualViewport = {
      height: 640,
      offsetTop: 24,
      addEventListener: vi.fn((type: string, listener: EventListener) => {
        const eventListeners = listeners.get(type) ?? new Set<EventListener>();
        eventListeners.add(listener);
        listeners.set(type, eventListeners);
      }),
      removeEventListener: vi.fn((type: string, listener: EventListener) => {
        listeners.get(type)?.delete(listener);
      }),
    };
    Object.defineProperty(window, "visualViewport", {
      configurable: true,
      value: visualViewport,
    });

    const { result, unmount } = renderHook(() => useVisualViewport());
    expect(result.current).toEqual({ height: 640, offsetTop: 24 });

    visualViewport.height = 600;
    visualViewport.offsetTop = 40;
    act(() =>
      listeners
        .get("scroll")
        ?.forEach((listener) => listener(new Event("scroll"))),
    );
    expect(result.current).toEqual({ height: 600, offsetTop: 40 });

    unmount();
    expect([...listeners.values()].every((events) => events.size === 0)).toBe(
      true,
    );
  });

  it("does not subscribe while disabled", () => {
    const addEventListener = vi.fn();
    Object.defineProperty(window, "visualViewport", {
      configurable: true,
      value: { height: 640, offsetTop: 24, addEventListener },
    });

    const { result } = renderHook(() => useVisualViewport(false));

    expect(result.current).toBeNull();
    expect(addEventListener).not.toHaveBeenCalled();
  });
});
