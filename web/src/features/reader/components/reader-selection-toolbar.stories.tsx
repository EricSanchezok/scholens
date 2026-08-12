import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { ReaderSelection } from "./pdf-page";
import { ReaderSelectionToolbar } from "./reader-selection-toolbar";

const selection: ReaderSelection = {
  kind: "paper_selection",
  document_id: "10000000-0000-4000-8000-000000000001",
  page_number: 4,
  selected_text:
    "Retrieval quality depends on ranking and context construction.",
  anchor: {
    kind: "pdf_text",
    page_number: 4,
    rects: [{ x: 0.24, y: 0.34, width: 0.48, height: 0.04 }],
  },
};

const meta = {
  title: "Reader/Selection toolbar",
  component: ReaderSelectionToolbar,
  args: {
    labels: {
      ask: "Ask about selection",
      comment: "Add annotation",
      copy: "Copy selection",
      copied: "Copied",
      copying: "Copying",
      copyFailed: "Copy failed",
      highlight: "Highlight selection",
      colors: {
        yellow: "Yellow highlight",
        blue: "Blue highlight",
        green: "Green highlight",
        neutral: "Neutral highlight",
      },
    },
    onAsk: fn(),
    onComment: fn(),
    onCopySettled: fn(),
    onHighlight: fn(),
    selection,
  },
  decorators: [
    (Story) => (
      <div className="bg-canvas relative h-[36rem] w-[28rem] max-w-full border">
        <p className="text-secondary absolute top-[34%] left-[24%] text-sm">
          Selected PDF text
        </p>
        <Story />
      </div>
    ),
  ],
  parameters: { layout: "centered" },
} satisfies Meta<typeof ReaderSelectionToolbar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SelectionToolbar: Story = {};

export const HighlightPalette: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Highlight selection" }),
    );
    await waitFor(() =>
      expect(
        canvas.getByRole("button", { name: "Yellow highlight" }),
      ).toBeVisible(),
    );
  },
};
