import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { http, HttpResponse } from "msw";
import type { Route } from "next";
import { expect, fn, userEvent, within } from "storybook/test";

import { ToastProvider } from "@/components/ui/toast";
import {
  PaperCollectionWorkbench,
  type PaperCollectionItem,
} from "./paper-collection-workbench";

const preferences = {
  preview_open: true,
  visible_columns: ["status", "tags", "authors", "publication", "last_opened"],
} as const;

const preferenceHandlers = [
  http.get("*/api/v1/me/paper-list-preferences", () =>
    HttpResponse.json(preferences),
  ),
  http.put("*/api/v1/me/paper-list-preferences", async ({ request }) =>
    HttpResponse.json(await request.json()),
  ),
];

const items: PaperCollectionItem[] = [
  {
    abstract:
      "A practical account of controllable memory formation and retrieval for adaptive agents.",
    addedAt: "Aug 20, 2026",
    authors: ["Eric Hanchen Jiang", "Zhi Zhang", "Yuchen Wu"],
    doi: "10.48550/arXiv.2608.12001",
    href: "/reader/00000000-0000-4000-8000-000000000001" as Route,
    id: "00000000-0000-4000-8000-000000000001",
    inLibrary: true,
    keywords: ["memory", "agents", "retrieval"],
    lastOpened: "Today, 14:32",
    publication: "arXiv · 2026",
    status: "reading",
    tags: [
      { id: "memory", name: "Memory" },
      { id: "agents", name: "Agents" },
      { id: "review", name: "Review" },
    ],
    title: "Memory as a Controlled Process: Learned Adaptive Memory for Agents",
  },
  {
    abstract: undefined,
    addedAt: "Aug 19, 2026",
    authors: [],
    href: "/reader/00000000-0000-4000-8000-000000000002" as Route,
    id: "00000000-0000-4000-8000-000000000002",
    inLibrary: true,
    keywords: [],
    publication: "NeurIPS · 2025",
    status: "todo",
    tags: [],
    title:
      "A deliberately long research paper title that exercises two-line truncation without sacrificing the identity of the paper",
  },
  {
    authors: ["Udit Sharma"],
    href: "/reader/00000000-0000-4000-8000-000000000003" as Route,
    id: "00000000-0000-4000-8000-000000000003",
    inLibrary: true,
    keywords: ["simulation"],
    lastOpened: "Yesterday",
    publication: "AAMAS · 2025",
    status: "completed",
    summary:
      "Paired stochastic realizations reduce variance when outcomes remain positively correlated.",
    tags: [{ id: "evaluation", name: "Evaluation" }],
    title: "When Does Pairing Seeds Reduce Variance?",
  },
];

const meta = {
  title: "Features/Paper Collection/Workbench",
  component: PaperCollectionWorkbench,
  args: {
    actions: () => <button type="button">•••</button>,
    items,
    onStatusChange: fn(),
    onTagClick: fn(),
  },
  parameters: {
    layout: "fullscreen",
    msw: { handlers: preferenceHandlers },
  },
  decorators: [
    (Story) => (
      <ToastProvider dismissLabel="Dismiss notification">
        <div className="mx-auto w-full max-w-[1680px] p-6">
          <Story />
        </div>
      </ToastProvider>
    ),
  ],
} satisfies Meta<typeof PaperCollectionWorkbench>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Library: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const paperLink = await canvas.findByRole("link", {
      name: /Memory as a Controlled Process/,
    });
    await expect(paperLink).toHaveAttribute(
      "href",
      "/reader/00000000-0000-4000-8000-000000000001",
    );
    const status = canvas.getAllByRole("button", {
      name: "Reading status",
    })[0]!;
    await userEvent.click(status);
    await expect(paperLink).toHaveAttribute(
      "href",
      "/reader/00000000-0000-4000-8000-000000000001",
    );
    await userEvent.keyboard("{Escape}");
  },
};

export const ProjectPapers: Story = {
  args: {
    items: [
      ...items,
      {
        authors: ["Project collaborator"],
        href: "/reader/00000000-0000-4000-8000-000000000004?project=project-1" as Route,
        id: "00000000-0000-4000-8000-000000000004",
        inLibrary: false,
        keywords: [],
        publication: "ICLR · 2026",
        tags: [],
        title: "A project paper that is not in my personal Library",
      },
    ],
    personalLabels: true,
  },
};

export const SearchResults: Story = {
  args: {
    items: items.map((item) => ({
      ...item,
      snippet: "…adaptive memory is updated through a controlled process…",
    })),
  },
};

export const Dark: Story = {
  globals: { appearance: "dark" },
};

export const Chinese: Story = {
  globals: { locale: "zh-CN" },
};

export const Narrow: Story = {
  parameters: { viewport: { defaultViewport: "tablet" } },
};

export const Mobile: Story = {
  parameters: { viewport: { defaultViewport: "mobile1" } },
};

export const ThousandPapers: Story = {
  args: {
    items: Array.from({ length: 1000 }, (_, index) => ({
      ...items[index % items.length]!,
      href: `/reader/paper-${index}` as Route,
      id: `paper-${index}`,
      title: `${index + 1}. ${items[index % items.length]!.title}`,
    })),
  },
};
