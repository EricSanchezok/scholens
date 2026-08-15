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

function ResponsiveFullDialogDemo() {
  return (
    <Dialog defaultOpen>
      <DialogContent closeLabel="Close settings" placement="responsive-full">
        <DialogTitle className="sr-only">Settings</DialogTitle>
        <DialogDescription className="sr-only">
          Responsive full-screen dialog placement
        </DialogDescription>
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <aside className="border-line bg-subtle shrink-0 border-b p-6 lg:w-64 lg:border-r lg:border-b-0">
            <h1 className="text-xl font-semibold">Settings</h1>
          </aside>
          <main className="min-h-0 flex-1 overflow-y-auto p-8">
            <h2 className="text-2xl font-semibold">General</h2>
            <p className="text-secondary mt-2 text-sm">
              Full-screen on mobile and centered at 1120 × 760 on desktop.
            </p>
          </main>
        </div>
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
export const ResponsiveFull: StoryObj<typeof ResponsiveFullDialogDemo> = {
  render: () => <ResponsiveFullDialogDemo />,
};
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
