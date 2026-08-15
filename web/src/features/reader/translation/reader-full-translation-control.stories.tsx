import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ReaderFullTranslationControl } from "./reader-full-translation-control";

const preferences = {
  auto_translate_selection: true,
  custom_instructions: null,
  full_translation_display: "bilingual" as const,
  show_translation_marker: true,
  source_language: "auto",
  target_language: "zh-CN",
  translate_references: false,
};

const meta = {
  title: "Reader/Translation/FullTranslationControl",
  component: ReaderFullTranslationControl,
  args: {
    enabled: true,
    onEnabledChange: fn(),
    onPreferencesChange: fn(async () => preferences),
    preferences,
    saving: false,
    status: "translating",
  },
  parameters: { layout: "centered" },
} satisfies Meta<typeof ReaderFullTranslationControl>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DesktopPopover: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /Full translation/ }),
    );
    const body = within(canvasElement.ownerDocument.body);
    await expect(body.getByText("Target language")).toBeVisible();
    await expect(body.getByText("Translate references")).toBeVisible();
  },
};

export const Completed: Story = {
  args: { status: "complete" },
};

export const PartialFailure: Story = {
  args: { status: "partial" },
};

export const MobileBottomSheet: Story = {
  globals: { viewport: { value: "smallMobile" } },
};

export const Dark: Story = {
  globals: { appearance: "dark" },
};
