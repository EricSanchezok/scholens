import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { PaperSearchResults } from "./paper-search-results";
import type { PaperSearchResult } from "./api";

const now = "2026-08-20T08:00:00Z";
const papers: PaperSearchResult[] = [
  {
    abstract:
      "The model learns program semantics from execution traces and uses them to improve code reasoning.",
    authors: ["Jade Copet", "Quentin Carbonneaux"],
    created_at: now,
    document_id: "00000000-0000-4000-8000-000000000001",
    last_accessed_at: now,
    matched_fields: ["semantic"],
    preview_url: null,
    publish_date: now,
    snippets: [
      {
        text: "Execution traces provide grounded supervision for a learned code world model.",
      },
    ],
    status: "completed",
    title: "CWM: An Open-Weights LLM for Code Generation with World Models",
  },
  {
    abstract:
      "A debugging framework identifies inconsistencies between generated programs and simulated execution.",
    authors: ["Babak Rahmani"],
    created_at: now,
    document_id: "00000000-0000-4000-8000-000000000002",
    last_accessed_at: now,
    matched_fields: ["title"],
    preview_url: null,
    publish_date: now,
    snippets: [],
    status: "completed",
    title: "Debugging Code World Models",
  },
];

const meta = {
  title: "Features/Paper Search/Results",
  component: PaperSearchResults,
  args: {
    hasMore: false,
    loading: false,
    loadingMore: false,
    onLoadMore: fn(async () => undefined),
    onRetry: fn(),
    papers,
    total: papers.length,
  },
} satisfies Meta<typeof PaperSearchResults>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Populated: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("2 matching papers")).toBeInTheDocument();
    await userEvent.tab();
    await expect(
      canvas.getByRole("link", {
        name: /CWM: An Open-Weights LLM/,
      }),
    ).toHaveFocus();
  },
};

export const Empty: Story = {
  args: { papers: [], total: 0 },
};

export const Loading: Story = {
  args: { loading: true, papers: [] },
};

export const Unavailable: Story = {
  args: { error: new Error("offline"), papers: [] },
};

export const Narrow: Story = {
  parameters: { viewport: { defaultViewport: "mobile1" } },
};
