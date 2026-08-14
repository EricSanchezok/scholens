import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { fn } from "storybook/test";

import { ReaderDocumentNavigation } from "./reader-document-navigation";

const outline = [
  {
    children: [],
    destination: "introduction",
    title: "1 Introduction",
  },
  {
    children: [
      {
        children: [],
        destination: "retrieval",
        title: "2.1 Retrieval",
      },
      {
        children: [],
        destination: "generation",
        title: "2.2 Generation",
      },
    ],
    destination: "method",
    title: "2 Method",
  },
];

const meta = {
  title: "Reader/ReaderDocumentNavigation",
  component: ReaderDocumentNavigation,
  args: {
    children: (
      <div className="grid gap-2">
        {[1, 2, 3].map((page) => (
          <button
            className="border-line bg-surface aspect-[3/4] rounded-[var(--radius-md)] border text-xs"
            key={page}
            type="button"
          >
            {page}
          </button>
        ))}
      </div>
    ),
    labels: {
      emptyOutline: "This PDF does not include an outline.",
      navigation: "Document navigation",
    },
    mode: "thumbnails",
    onOutlineSelect: fn(),
    outline,
  },
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof ReaderDocumentNavigation>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Pages: Story = {};

export const Outline: Story = {
  args: { mode: "outline" },
};

export const EmptyOutline: Story = {
  args: { mode: "outline", outline: [] },
};
