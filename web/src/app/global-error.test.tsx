import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GlobalErrorFallback } from "./global-error";

describe("global error fallback", () => {
  it("remains readable and retryable without theme classes", () => {
    const reset = vi.fn();
    render(<GlobalErrorFallback reset={reset} />);

    const surface = screen.getByRole("main");
    const retry = screen.getByRole("button", { name: "Try again" });

    expect(surface).not.toHaveAttribute("class");
    expect(surface).toHaveStyle({ minHeight: "100dvh" });
    expect(
      screen.getByRole("heading", { name: "Scholens could not start" }),
    ).toBeVisible();
    expect(screen.getByText("Try the startup sequence again.")).toBeVisible();
    expect(retry).toHaveStyle({ minHeight: "44px" });

    fireEvent.click(retry);
    expect(reset).toHaveBeenCalledOnce();
  });

  it("keeps the optional raven artwork decorative and separate from recovery", () => {
    render(<GlobalErrorFallback reset={() => undefined} />);

    const artwork = document.querySelector<HTMLElement>(
      "[data-global-error-artwork]",
    );
    expect(artwork).toHaveAttribute("aria-hidden", "true");
    expect(artwork?.style.backgroundImage).toContain(
      "/brand/scholens-raven-portrait-128.png",
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});
