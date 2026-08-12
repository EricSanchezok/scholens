import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { fn } from "storybook/test";

import { ResearchComposer } from "./research-composer";

const meta = {
  title: "Conversation/ResearchComposer",
  component: ResearchComposer,
  args: {
    context: { kind: "library" },
    onContextChange: fn(),
    onReasoningLevelChange: fn(),
    onStop: fn(),
    onSubmit: fn(async () => undefined),
    papers: [],
    projects: [],
    reasoningLevel: "standard",
  },
  decorators: [
    (Story) => (
      <main className="flex min-h-dvh items-end p-3">
        <Story />
      </main>
    ),
  ],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ResearchComposer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Desktop: Story = {};

export const Mobile: Story = {
  globals: { viewport: { value: "mobile1" } },
};

export const Streaming: Story = {
  args: { busy: true },
};
