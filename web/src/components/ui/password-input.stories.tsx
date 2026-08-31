import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import {
  expectQuietPointerFocus,
  readFocusVisual,
} from "./focus-contract.story-test";
import { PasswordInput } from "./input";

const meta = {
  title: "Forms/PasswordInput",
  component: PasswordInput,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: {
    "aria-label": "Password",
    hidePasswordLabel: "Hide password",
    showPasswordLabel: "Show password",
  },
  decorators: [
    (Story) => (
      <div className="w-[min(90vw,24rem)]">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof PasswordInput>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const CompactHoverAffordance: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Show password" });
    const affordance = canvasElement.querySelector<HTMLElement>(
      '[data-slot="password-visibility-affordance"]',
    );
    await expect(affordance).not.toBeNull();
    if (!affordance) return;
    await expect(button.getBoundingClientRect().width).toBe(44);
    await expect(affordance.getBoundingClientRect().width).toBe(32);
  },
};

export const QuietPointerHover: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByLabelText("Password");
    const surface = input.closest<HTMLElement>("[data-focus-surface]");
    await expect(surface).not.toBeNull();
    if (!surface) return;

    const resting = readFocusVisual(surface);
    await userEvent.hover(input);
    await expectQuietPointerFocus({ element: surface, resting });
  },
};

export const AllStates: Story = {
  render: (args) => (
    <div className="grid gap-3">
      <PasswordInput {...args} placeholder="At least 12 characters" />
      <PasswordInput {...args} aria-invalid defaultValue="short" />
      <PasswordInput {...args} disabled value="unavailable" readOnly />
    </div>
  ),
};
export const KeyboardInteraction: Story = {
  args: { defaultValue: "twelve-characters" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByDisplayValue("twelve-characters")).toHaveAttribute(
      "type",
      "text",
    );
  },
};
