import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Badge } from "./display";
import { Frame, FramePanel } from "./frame";

const meta = {
  title: "Components/Frame",
  component: Frame,
  tags: ["autodocs"],
  parameters: { layout: "padded" },
} satisfies Meta<typeof Frame>;

export default meta;
type Story = StoryObj<typeof meta>;

export const RaisedPanels: Story = {
  render: () => (
    <Frame className="max-w-xl">
      <FramePanel className="grid gap-1">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">Research workspace</h2>
          <Badge>Active</Badge>
        </div>
        <p className="text-secondary text-sm leading-5 text-pretty">
          One quiet frame groups related content while the raised panel carries
          the interactive surface.
        </p>
      </FramePanel>
      <FramePanel
        className="flex items-center justify-between gap-3"
        spacing="compact"
      >
        <span className="text-sm font-medium">18 papers</span>
        <span className="text-secondary text-xs">Updated today</span>
      </FramePanel>
    </Frame>
  ),
};

export const CompactNarrow: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  render: () => (
    <Frame className="max-w-sm" spacing="compact">
      <FramePanel className="grid gap-1" spacing="compact">
        <h2 className="truncate text-sm font-semibold">
          Retrieval–Augmented Generation for Knowledge–Intensive NLP Tasks
        </h2>
        <p className="text-secondary text-xs">8 papers · Updated yesterday</p>
      </FramePanel>
    </Frame>
  ),
};
