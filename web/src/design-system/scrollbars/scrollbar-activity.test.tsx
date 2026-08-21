import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ScrollbarActivity,
  scrollbarActivityAttribute,
  scrollbarIdleDelayMs,
} from "./scrollbar-activity";

describe("ScrollbarActivity", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reveals only the scroller that is active and hides it after idle", () => {
    vi.useFakeTimers();
    const { getByTestId } = render(
      <>
        <ScrollbarActivity />
        <div data-testid="first-scroller" />
        <div data-testid="second-scroller" />
      </>,
    );
    const first = getByTestId("first-scroller");
    const second = getByTestId("second-scroller");

    act(() => first.dispatchEvent(new Event("scroll")));

    expect(first).toHaveAttribute(scrollbarActivityAttribute);
    expect(second).not.toHaveAttribute(scrollbarActivityAttribute);

    act(() => vi.advanceTimersByTime(scrollbarIdleDelayMs - 1));
    expect(first).toHaveAttribute(scrollbarActivityAttribute);

    act(() => vi.advanceTimersByTime(1));
    expect(first).not.toHaveAttribute(scrollbarActivityAttribute);
  });

  it("restarts the idle interval when scrolling continues", () => {
    vi.useFakeTimers();
    const { getByTestId } = render(
      <>
        <ScrollbarActivity />
        <div data-testid="scroller" />
      </>,
    );
    const scroller = getByTestId("scroller");

    act(() => scroller.dispatchEvent(new Event("scroll")));
    act(() => vi.advanceTimersByTime(scrollbarIdleDelayMs - 100));
    act(() => scroller.dispatchEvent(new Event("scroll")));
    act(() => vi.advanceTimersByTime(100));

    expect(scroller).toHaveAttribute(scrollbarActivityAttribute);

    act(() => vi.advanceTimersByTime(scrollbarIdleDelayMs - 100));
    expect(scroller).not.toHaveAttribute(scrollbarActivityAttribute);
  });

  it("maps document scrolling to the root scrolling element", () => {
    vi.useFakeTimers();
    render(<ScrollbarActivity />);

    act(() => document.dispatchEvent(new Event("scroll")));

    expect(
      document.scrollingElement ?? document.documentElement,
    ).toHaveAttribute(scrollbarActivityAttribute);

    act(() => vi.advanceTimersByTime(scrollbarIdleDelayMs));
    expect(
      document.scrollingElement ?? document.documentElement,
    ).not.toHaveAttribute(scrollbarActivityAttribute);
  });

  it("shares one document listener across nested provider consumers", () => {
    const addEventListener = vi.spyOn(document, "addEventListener");
    const removeEventListener = vi.spyOn(document, "removeEventListener");
    const { rerender, unmount } = render(
      <>
        <ScrollbarActivity />
        <ScrollbarActivity />
      </>,
    );

    expect(
      addEventListener.mock.calls.filter(([type]) => type === "scroll"),
    ).toHaveLength(1);

    rerender(<ScrollbarActivity />);
    expect(
      removeEventListener.mock.calls.filter(([type]) => type === "scroll"),
    ).toHaveLength(0);

    unmount();
    expect(
      removeEventListener.mock.calls.filter(([type]) => type === "scroll"),
    ).toHaveLength(1);
  });
});
