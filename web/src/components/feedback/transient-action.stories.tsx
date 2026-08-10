import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Check, Copy, WarningCircle } from "iconoir-react";
import { expect, fn, userEvent, within } from "storybook/test";

import { TransientActionIconButton } from "./transient-action";

const labels = {
  idle: "Copy answer",
  pending: "Copying answer",
  success: "Answer copied",
  error: "Could not copy answer",
};

const meta = {
  title: "Feedback/Transient Action",
  component: TransientActionIconButton,
  args: {
    action: fn(async () => undefined),
    errorGlyph: WarningCircle,
    glyph: Copy,
    labels,
    successGlyph: Check,
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-40 items-start justify-center p-8">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof TransientActionIconButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Success: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(canvas.getByRole("button", { name: labels.idle }));
    await expect(
      canvas.getByRole("button", { name: labels.success }),
    ).toBeVisible();
    await expect(page.getAllByText(labels.success)[0]).toBeVisible();
  },
};

export const Failure: Story = {
  args: {
    action: fn(async () => {
      throw new Error("Clipboard denied");
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(canvas.getByRole("button", { name: labels.idle }));
    await expect(
      canvas.getByRole("button", { name: labels.error }),
    ).toBeVisible();
    await expect(page.getAllByText(labels.error)[0]).toBeVisible();
  },
};

export const Disabled: Story = {
  args: { disabled: true },
};
