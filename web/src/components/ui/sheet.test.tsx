import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Sheet, SheetContent, SheetTitle } from "./sheet";

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

describe("SheetContent", () => {
  it("aligns visual-full sheets to the visible viewport", async () => {
    Object.defineProperty(window, "visualViewport", {
      configurable: true,
      value: {
        addEventListener: vi.fn(),
        height: 560,
        offsetTop: 48,
        removeEventListener: vi.fn(),
      },
    });

    render(
      <Sheet open>
        <SheetContent
          closeLabel="Close panel"
          placement="visual-full"
          showCloseButton={false}
        >
          <SheetTitle>Visible panel</SheetTitle>
        </SheetContent>
      </Sheet>,
    );

    const panel = screen.getByRole("dialog", { name: "Visible panel" });
    await waitFor(() => {
      expect(panel).toHaveStyle({
        blockSize: "560px",
        insetBlockEnd: "auto",
        insetBlockStart: "48px",
      });
    });
    expect(panel).toHaveAttribute("data-placement", "visual-full");
    expect(panel).toHaveClass("pt-[env(safe-area-inset-top)]");
    expect(panel).toHaveClass("pb-[env(safe-area-inset-bottom)]");
  });

  it("keeps side sheets on their existing layout viewport contract", () => {
    render(
      <Sheet open>
        <SheetContent closeLabel="Close panel" side="left">
          <SheetTitle>Side panel</SheetTitle>
        </SheetContent>
      </Sheet>,
    );

    const panel = screen.getByRole("dialog", { name: "Side panel" });
    expect(panel).toHaveAttribute("data-placement", "side");
    expect(panel).toHaveAttribute("data-side", "left");
    expect(panel.style.blockSize).toBe("");
  });
});
