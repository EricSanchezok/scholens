import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";

import { Button } from "./button";
import { ToastProvider, useToast } from "./toast";

function ToastDemo() {
  const toast = useToast();
  return (
    <Button
      onClick={() =>
        toast.notify({ title: "Saved", description: "Your changes are ready." })
      }
    >
      Show toast
    </Button>
  );
}

const meta = {
  title: "Feedback/Toast",
  component: ToastDemo,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  decorators: [
    (Story) => (
      <ToastProvider dismissLabel="Dismiss notification">
        <Story />
      </ToastProvider>
    ),
  ],
} satisfies Meta<typeof ToastDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const SwipeRight: Story = {
  globals: { motion: "full" },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Show toast" }),
    );
    const body = within(document.body);
    const title = await body.findByText("Saved");
    const toast = title.closest<HTMLElement>("[data-state]");
    await expect(toast).not.toBeNull();
    await expect(toast).toHaveAttribute("data-swipe-direction", "right");
    toast!.setPointerCapture = () => undefined;
    toast!.hasPointerCapture = () => true;
    toast!.releasePointerCapture = () => undefined;
    let exitAnimation = "";
    toast!.addEventListener("animationstart", (event) => {
      if (event.animationName === "motion-toast-swipe-out") {
        exitAnimation = event.animationName;
      }
    });

    await fireEvent.pointerDown(toast!, {
      button: 0,
      clientX: 100,
      clientY: 100,
      pointerId: 1,
      pointerType: "mouse",
    });
    await fireEvent.pointerMove(toast!, {
      clientX: 110,
      clientY: 100,
      pointerId: 1,
      pointerType: "mouse",
    });
    await fireEvent.pointerMove(toast!, {
      clientX: 140,
      clientY: 100,
      pointerId: 1,
      pointerType: "mouse",
    });
    await waitFor(() => {
      expect(toast).toHaveAttribute("data-swipe", "move");
      const matrix = new DOMMatrixReadOnly(getComputedStyle(toast!).transform);
      expect(matrix.m41).toBeCloseTo(40, 1);
      expect(matrix.m42).toBeCloseTo(0, 1);
    });
    await fireEvent.pointerUp(toast!, {
      clientX: 140,
      clientY: 100,
      pointerId: 1,
      pointerType: "mouse",
    });
    await expect(toast).toHaveAttribute("data-swipe", "cancel");
    await waitFor(() => {
      const matrix = new DOMMatrixReadOnly(getComputedStyle(toast!).transform);
      expect(matrix.m41).toBeCloseTo(0, 1);
      expect(matrix.m42).toBeCloseTo(0, 1);
    });

    await fireEvent.pointerDown(toast!, {
      button: 0,
      clientX: 100,
      clientY: 100,
      pointerId: 2,
      pointerType: "mouse",
    });
    await fireEvent.pointerMove(toast!, {
      clientX: 110,
      clientY: 100,
      pointerId: 2,
      pointerType: "mouse",
    });
    await fireEvent.pointerMove(toast!, {
      clientX: 180,
      clientY: 100,
      pointerId: 2,
      pointerType: "mouse",
    });
    await fireEvent.pointerUp(toast!, {
      clientX: 180,
      clientY: 100,
      pointerId: 2,
      pointerType: "mouse",
    });
    await expect(toast).toHaveAttribute("data-swipe", "end");
    await waitFor(() => expect(exitAnimation).toBe("motion-toast-swipe-out"));
    await waitFor(() => expect(title).not.toBeInTheDocument());
  },
};
export const MobileLongContent: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};
