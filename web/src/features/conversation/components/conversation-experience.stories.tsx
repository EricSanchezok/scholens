import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { fn } from "storybook/test";

import { ResearchComposer } from "./research-composer";

const meta = {
  title: "Conversation/ResearchComposer",
  component: ResearchComposer,
  args: {
    context: { kind: "library" },
    surface: "workspace",
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
  globals: { viewport: { value: "mobile" } },
};

export const Streaming: Story = {
  args: { busy: true },
};

export const ContextPanelSelection: Story = {
  args: {
    context: {
      kind: "selection",
      document_ids: ["paper-1"],
      project_ids: [],
    },
    contextLabel: "Retrieval-Augmented Generation",
    onTurnContextClear: fn(),
    surface: "context-panel",
    turnContextLabel: "Page 4 selection",
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-dvh items-end justify-end p-3">
        <div className="w-[23rem] max-w-full">
          <Story />
        </div>
      </div>
    ),
  ],
};
