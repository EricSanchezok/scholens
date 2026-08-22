import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./dropdown-menu";
import { OverflowMenuButton } from "./overflow-menu-button";

const meta = {
  title: "Actions/OverflowMenuButton",
  component: OverflowMenuButton,
  args: { label: "Open actions" },
  parameters: { layout: "centered" },
  tags: ["autodocs"],
} satisfies Meta<typeof OverflowMenuButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AlwaysVisible: Story = {};

export const Contextual: Story = {
  args: { visibility: "contextual" },
  render: (args) => (
    <div className="group/interactive-row hover:bg-hover focus-within:bg-hover flex w-72 items-center gap-3 rounded-[var(--radius-lg)] px-3 py-2">
      <span className="min-w-0 flex-1 truncate text-sm">
        A long research conversation title
      </span>
      <OverflowMenuButton {...args} />
    </div>
  ),
};

export const MobileContextual: Story = {
  ...Contextual,
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", {
      name: "Open actions",
    });
    await expect(button).toBeVisible();
    await expect(getComputedStyle(button).opacity).toBe("1");
  },
};

export const Open: Story = {
  render: (args) => (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <OverflowMenuButton {...args} />
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuItem>Rename</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  ),
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Open actions" }),
    );
    await expect(
      await within(document.body).findByRole("menuitem", { name: "Rename" }),
    ).toBeVisible();
  },
};
