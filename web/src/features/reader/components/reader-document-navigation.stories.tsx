import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { ReaderDocumentNavigation } from "./reader-document-navigation";

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
    label: "Page thumbnails",
  },
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof ReaderDocumentNavigation>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Pages: Story = {};
