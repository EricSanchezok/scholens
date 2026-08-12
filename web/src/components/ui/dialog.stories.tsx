import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { Button } from "./button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./dialog";

function DialogDemo() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="secondary">Open dialog</Button>
      </DialogTrigger>
      <DialogContent closeLabel="Close dialog">
        <DialogHeader>
          <DialogTitle>Confirm your email</DialogTitle>
          <DialogDescription>
            We will send a verification link to your account email.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <p className="text-secondary text-sm">
            This content area owns scrolling and preserves the dialog padding.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button>Send verification link</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const meta = {
  title: "Overlays/Dialog",
  component: DialogDemo,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
} satisfies Meta<typeof DialogDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const KeyboardInteraction: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Open dialog" }));
    await expect(within(document.body).getByRole("dialog")).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await expect(
      within(document.body).queryByRole("dialog"),
    ).not.toBeInTheDocument();
  },
};
