import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ReaderMobileReflowNudge } from "./reader-mobile-reflow-nudge";

const meta = {
  title: "Reader/MobileReflowNudge",
  component: ReaderMobileReflowNudge,
  args: { onDismiss: fn(), onOpenReflow: fn() },
  globals: { viewport: { value: "mobile" } },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ReaderMobileReflowNudge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Mobile: Story = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Try AI reflow" }),
    );
    await expect(args.onOpenReflow).toHaveBeenCalledOnce();
  },
};

export const SmallMobileChineseDark: Story = {
  globals: {
    appearance: "dark",
    locale: "zh-CN",
    viewport: { value: "smallMobile" },
  },
};
