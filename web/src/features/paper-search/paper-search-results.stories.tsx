import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useTranslations } from "next-intl";
import * as React from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";

import { SearchField } from "@/components/ui";
import { ToastProvider } from "@/components/ui/toast";
import {
  CollectionToolbar,
  PaperCollectionWorkbench,
} from "@/features/paper-collection";
import type { PaperSearchResult } from "./api";
import { usePaperSearchWorkbench } from "./use-paper-search-workbench";

const now = "2026-08-20T08:00:00Z";
const hostileSnippet = [
  "## **Matched passage about code world models**",
  "<!-- private extraction note --><script>hidden()</script>",
  "<p>Execution traces provide [grounded supervision](https://example.test) &amp; stable evidence.</p>",
  "| Method | Result |\n| --- | --- |\n| simulation | improved reasoning |",
  "\u0000\u0007",
  "Detailed experimental evidence with multilingual terms 世界 and emoji 👩🏽‍💻. ".repeat(
    24,
  ),
].join("\n");

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
    snippets: [{ text: hostileSnippet }],
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
const manyPapers = Array.from({ length: 24 }, (_, index) => {
  const paper = papers[index % papers.length]!;
  return {
    ...paper,
    document_id: `60000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    title: `${paper.title} · result ${index + 1}`,
  };
});

type ResultsStoryProps = {
  error?: unknown;
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  onLoadMore: () => Promise<void>;
  onRetry: () => void;
  papers: PaperSearchResult[];
  total?: number;
};

function ResultsStorySurface({
  error,
  hasMore,
  loading,
  loadingMore,
  onLoadMore,
  onRetry,
  papers: storyPapers,
  total,
}: ResultsStoryProps) {
  const t = useTranslations("PaperSearch.results");
  const searchWorkbench = usePaperSearchWorkbench({
    enabled: true,
    error,
    hasMore,
    loading,
    loadingMore,
    onLoadMore,
    onRetry,
    papers: storyPapers,
  });

  return (
    <div className="h-[36rem] min-h-0 min-w-0">
      <PaperCollectionWorkbench
        {...searchWorkbench!}
        toolbar={
          <CollectionToolbar
            controls={null}
            meta={
              !loading && !error && storyPapers.length > 0
                ? t("count", { count: total ?? storyPapers.length })
                : undefined
            }
            search={
              <SearchField aria-label="Search papers" defaultValue="code" />
            }
          />
        }
      />
    </div>
  );
}

const meta = {
  title: "Features/Paper Search/Results",
  component: ResultsStorySurface,
  args: {
    hasMore: false,
    loading: false,
    loadingMore: false,
    onLoadMore: fn(async () => undefined),
    onRetry: fn(),
    papers,
    total: papers.length,
  },
  decorators: [
    (Story) => (
      <ToastProvider dismissLabel="Dismiss notification">
        <Story />
      </ToastProvider>
    ),
  ],
} satisfies Meta<typeof ResultsStorySurface>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Populated: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("2 matching papers")).toBeInTheDocument();
    const paperLink = canvas.getByRole("link", {
      name: /CWM: An Open-Weights LLM/,
    });
    const snippet = await canvas.findByText(
      /Matched passage about code world models/,
    );
    const row = snippet.closest('[role="row"]');
    const textSlot = snippet.closest("[data-paper-result-text]");
    const rows = canvasElement.querySelectorAll('[role="row"][data-index]');

    await expect(row).not.toBeNull();
    await expect(textSlot).not.toBeNull();
    await expect(canvasElement.textContent).not.toContain("<script>");
    await expect(canvasElement.textContent).not.toContain("hidden()");
    await expect(getComputedStyle(snippet).webkitLineClamp).toBe("1");
    await expect(getComputedStyle(snippet).display).not.toBe("block");
    await expect(
      row?.getBoundingClientRect().height ?? 0,
    ).toBeGreaterThanOrEqual(63);
    await expect(row?.getBoundingClientRect().height ?? 0).toBeLessThanOrEqual(
      65,
    );
    await expect(
      Array.from(
        new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(
          snippet.textContent ?? "",
        ),
      ).length,
    ).toBeLessThanOrEqual(320);
    await expect(snippet.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      (textSlot?.getBoundingClientRect().bottom ?? 0) + 1,
    );
    await expect(
      textSlot?.getBoundingClientRect().bottom ?? 0,
    ).toBeLessThanOrEqual((row?.getBoundingClientRect().bottom ?? 0) + 1);
    if (rows.length > 1) {
      await expect(
        rows[0]?.getBoundingClientRect().bottom ?? 0,
      ).toBeLessThanOrEqual(rows[1]?.getBoundingClientRect().top ?? 0);
    }

    paperLink.focus();
    await expect(paperLink).toHaveFocus();
    await userEvent.keyboard("{Enter}");
  },
};

export const Empty: Story = {
  args: { papers: [], total: 0 },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("searchbox", { name: "Search papers" }),
    ).toBeInTheDocument();
  },
};

export const Loading: Story = {
  args: { loading: true, papers: [] },
  play: Empty.play,
};

export const Unavailable: Story = {
  args: { error: new Error("offline"), papers: [] },
  play: Empty.play,
};

export const Narrow: Story = {
  parameters: { viewport: { defaultViewport: "mobile1" } },
};

type AsyncState = "browse" | "loading" | "error" | "empty" | "success";
const asyncStates: AsyncState[] = [
  "browse",
  "loading",
  "error",
  "empty",
  "success",
];

function StableToolbarHarness() {
  const [stateIndex, setStateIndex] = React.useState(0);
  const state = asyncStates[stateIndex] ?? "browse";
  const searchWorkbench = usePaperSearchWorkbench({
    enabled: state !== "browse",
    error: state === "error" ? new Error("offline") : undefined,
    hasMore: false,
    loading: state === "loading",
    loadingMore: false,
    onLoadMore: async () => undefined,
    onRetry: () => undefined,
    papers: state === "success" ? papers : [],
  });

  return (
    <div className="grid h-[36rem] min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-3">
      <button
        onClick={() =>
          setStateIndex((current) =>
            Math.min(current + 1, asyncStates.length - 1),
          )
        }
        type="button"
      >
        Next result state
      </button>
      <PaperCollectionWorkbench
        {...(searchWorkbench ?? {
          contentState: <p className="p-4">Browse collection</p>,
          items: [],
        })}
        toolbar={
          <CollectionToolbar
            controls={null}
            search={
              <SearchField
                aria-label="Persistent paper search"
                defaultValue="code"
              />
            }
          />
        }
      />
    </div>
  );
}

export const StableToolbarAcrossStates: Story = {
  render: () => <StableToolbarHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const search = canvas.getByRole("searchbox", {
      name: "Persistent paper search",
    });
    await userEvent.type(search, "world");

    for (let index = 0; index < 4; index += 1) {
      await userEvent.click(
        canvas.getByRole("button", { name: "Next result state" }),
      );
      const current = canvas.getByRole("searchbox", {
        name: "Persistent paper search",
      });
      await expect(current).toBe(search);
      await expect(current).toHaveValue("codeworld");
    }
    await expect(
      canvas.getByRole("link", { name: /CWM: An Open-Weights LLM/ }),
    ).toBeVisible();
  },
};

function ScrollResetHarness() {
  const [phase, setPhase] = React.useState<"ready" | "loading" | "resolved">(
    "ready",
  );
  const searchWorkbench = usePaperSearchWorkbench({
    enabled: true,
    hasMore: false,
    loading: phase === "loading",
    loadingMore: false,
    onLoadMore: async () => undefined,
    onRetry: () => undefined,
    papers: manyPapers,
  });

  return (
    <div className="grid h-[36rem] min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-3">
      <button
        disabled={phase === "resolved"}
        onClick={() =>
          setPhase((current) => (current === "ready" ? "loading" : "resolved"))
        }
        type="button"
      >
        {phase === "ready" ? "Commit next search" : "Resolve next search"}
      </button>
      <PaperCollectionWorkbench
        {...searchWorkbench!}
        scrollResetKey={phase === "ready" ? "browse" : "committed-search"}
        toolbar={
          <CollectionToolbar
            controls={null}
            search={
              <SearchField
                aria-label="Scroll-stable paper search"
                defaultValue="code"
              />
            }
          />
        }
      />
    </div>
  );
}

export const ResetsResultScrollOnCommittedSearch: Story = {
  render: () => <ScrollResetHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const search = canvas.getByRole("searchbox", {
      name: "Scroll-stable paper search",
    });
    const scroller = canvasElement.querySelector<HTMLElement>(
      "[data-paper-collection-scroll]",
    );
    await expect(scroller).not.toBeNull();
    if (!scroller) return;

    await userEvent.type(search, "world");
    scroller.scrollTop = 480;
    await fireEvent.scroll(scroller);
    await expect(scroller.scrollTop).toBeGreaterThan(0);
    await userEvent.click(
      canvas.getByRole("button", { name: "Commit next search" }),
    );
    await expect(
      canvas.getByRole("searchbox", { name: "Scroll-stable paper search" }),
    ).toBe(search);
    await userEvent.click(
      canvas.getByRole("button", { name: "Resolve next search" }),
    );

    await expect(scroller.scrollTop).toBe(0);
    await expect(
      canvas.getByRole("searchbox", { name: "Scroll-stable paper search" }),
    ).toBe(search);
    await expect(search).toHaveValue("codeworld");
    await expect(
      canvas.getByRole("link", {
        name: /^CWM: An Open-Weights LLM for Code Generation with World Models · result 1 /,
      }),
    ).toBeVisible();
  },
};
