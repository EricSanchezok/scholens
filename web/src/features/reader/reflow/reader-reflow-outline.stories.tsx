import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ReaderReflowOutline } from "./reader-reflow-outline";

const onSelect = fn();
const entries = [
  { id: "abstract", label: "Abstract", level: 2 },
  { id: "introduction", label: "1 Introduction", level: 2 },
  { id: "method", label: "2 Method", level: 2 },
  { id: "retrieval", label: "2.1 Retrieval", level: 3 },
  {
    id: "dense-retrieval",
    label: "2.1.1 Dense retrieval across multilingual scientific collections",
    level: 4,
  },
  { id: "generation", label: "2.2 Generation", level: 3 },
  { id: "results", label: "3 Results", level: 2 },
];

const meta = {
  title: "Reader/Reflow/ReaderReflowOutline",
  component: ReaderReflowOutline,
  args: {
    entries,
    label: "Document outline",
    onSelect,
  },
  decorators: [
    (Story) => (
      <div className="border-line bg-canvas h-[34rem] w-64 overflow-y-auto border-r">
        <Story />
      </div>
    ),
  ],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ReaderReflowOutline>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DesktopSidebar: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "2.1 Retrieval" }),
    );
    await expect(onSelect).toHaveBeenCalledWith("retrieval");
  },
};

export const Narrow: Story = {
  decorators: [
    (Story) => (
      <div className="bg-elevated h-[30rem] w-80 overflow-y-auto">
        <Story />
      </div>
    ),
  ],
  globals: { viewport: { value: "smallMobile" } },
};

export const Dark: Story = {
  globals: { appearance: "dark" },
};
