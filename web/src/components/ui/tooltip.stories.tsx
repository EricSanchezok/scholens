import { InfoCircle } from "iconoir-react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { Icon } from "@/design-system/icons/icon";
import { IconButton } from "./button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./tooltip-popover";

function TooltipDemo() {
  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>
          <IconButton label="More information" variant="secondary">
            <Icon glyph={InfoCircle} size={20} />
          </IconButton>
        </TooltipTrigger>
        <TooltipContent>More information</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

const meta = {
  title: "Overlays/Tooltip",
  component: TooltipDemo,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
} satisfies Meta<typeof TooltipDemo>;

export default meta;
type Story = StoryObj<typeof meta>;
export const Playground: Story = {
  globals: { motion: "full" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.hover(
      canvas.getByRole("button", { name: "More information" }),
    );
    const tooltip = await within(document.body).findByRole("tooltip", {
      name: "More information",
    });
    await waitFor(() => expect(tooltip).toBeVisible());
    await expect(["delayed-open", "instant-open"]).toContain(
      tooltip.getAttribute("data-state"),
    );
    await expect(getComputedStyle(tooltip).animationName).toBe(
      "motion-popup-in",
    );
    const style = getComputedStyle(tooltip);
    const radixOrigin = style
      .getPropertyValue("--radix-tooltip-content-transform-origin")
      .trim();
    await expect(radixOrigin).not.toBe("");
    const [originX = Number.NaN, originY = Number.NaN] = style.transformOrigin
      .split(" ")
      .map((value) => Number.parseFloat(value));
    await expect(
      Math.abs(originX - tooltip.getBoundingClientRect().width / 2),
    ).toBeLessThan(0.5);
    await expect(originY).toBeCloseTo(0, 1);
  },
};
