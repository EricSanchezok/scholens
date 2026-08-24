import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { delay, http, HttpResponse } from "msw";
import type { Route } from "next";
import * as React from "react";
import {
  expect,
  fireEvent,
  fn,
  userEvent,
  waitFor,
  within,
} from "storybook/test";

import { ToastProvider } from "@/components/ui/toast";
import {
  PaperCollectionWorkbench,
  type PaperCollectionItem,
} from "./paper-collection-workbench";
import { defaultPaperListPreferences, type PaperListPreferences } from "./api";

const preferences: PaperListPreferences = {
  ...defaultPaperListPreferences,
  column_widths: defaultPaperListPreferences.column_widths.map((width) => ({
    ...width,
  })),
  preview_open: true,
  visible_columns: [
    "reading_time",
    "status",
    "tags",
    "authors",
    "publication",
    "last_opened",
  ],
};

const preferenceHandlers = [
  http.get("*/api/v1/me/paper-list-preferences", () =>
    HttpResponse.json(preferences),
  ),
  http.put("*/api/v1/me/paper-list-preferences", async ({ request }) =>
    HttpResponse.json(await request.json()),
  ),
];

let resizePreferenceRequestCount = 0;
let resizedPreferences = preferences;

const resizePreferenceHandlers = [
  http.get("*/api/v1/me/paper-list-preferences", () =>
    HttpResponse.json(preferences),
  ),
  http.put("*/api/v1/me/paper-list-preferences", async ({ request }) => {
    resizedPreferences = (await request.json()) as PaperListPreferences;
    resizePreferenceRequestCount += 1;
    return HttpResponse.json(resizedPreferences);
  }),
];

let queuedPreferenceRequestCount = 0;
let queuedPersistedPreferences: PaperListPreferences = {
  ...preferences,
  visible_columns: [...preferences.visible_columns],
};

const queuedPreferenceHandlers = [
  http.get("*/api/v1/me/paper-list-preferences", () =>
    HttpResponse.json(preferences),
  ),
  http.put("*/api/v1/me/paper-list-preferences", async ({ request }) => {
    const next = (await request.json()) as PaperListPreferences;
    queuedPreferenceRequestCount += 1;
    if (queuedPreferenceRequestCount === 1) await delay(200);
    queuedPersistedPreferences = next;
    return HttpResponse.json(next);
  }),
];

let failedPreferenceRequestCount = 0;

const failingPreferenceHandlers = [
  http.get("*/api/v1/me/paper-list-preferences", async () => {
    await delay(2000);
    return HttpResponse.json(preferences);
  }),
  http.put("*/api/v1/me/paper-list-preferences", async () => {
    failedPreferenceRequestCount += 1;
    if (failedPreferenceRequestCount === 1) await delay(200);
    return HttpResponse.json(
      { code: "preferences_unavailable" },
      { status: 503 },
    );
  }),
];

const items: PaperCollectionItem[] = [
  {
    abstract:
      "A practical account of controllable memory formation and retrieval for adaptive agents.",
    activityTrail: (
      <span
        aria-label="Page reading distribution"
        className="block h-1.5 bg-[linear-gradient(90deg,var(--color-activity-peak),transparent,var(--color-activity-medium))]"
        role="img"
      />
    ),
    addedAt: "Aug 20, 2026",
    authors: ["Eric Hanchen Jiang", "Zhi Zhang", "Yuchen Wu"],
    doi: "10.48550/arXiv.2608.12001",
    href: "/reader/00000000-0000-4000-8000-000000000001" as Route,
    id: "00000000-0000-4000-8000-000000000001",
    inLibrary: true,
    keywords: ["memory", "agents", "retrieval"],
    lastOpened: "Today, 14:32",
    publication: "arXiv · 2026",
    readingTime: "18 min",
    summary:
      "## Key findings\n\n**Controlled memory** improves retrieval quality.\n\n- Stable updates\n- Inspectable decisions",
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

const scrollingItems = Array.from({ length: 36 }, (_, index) => {
  const source = items[index % items.length]!;
  const suffix = String(index + 1).padStart(12, "0");
  return {
    ...source,
    href: `/reader/00000000-0000-4000-8000-${suffix}` as Route,
    id: `00000000-0000-4000-8000-${suffix}`,
    title: `${index + 1}. ${source.title}`,
  };
});

const meta = {
  title: "Features/Paper Collection/Workbench",
  component: PaperCollectionWorkbench,
  args: {
    actions: () => <button type="button">•••</button>,
    items,
    onStatusChange: fn(),
    onTagClick: fn(),
    toolbar: (
      <div className="flex min-w-0 items-center gap-3">
        <span className="text-secondary text-sm">Search and filters</span>
        <span className="text-secondary ml-auto text-xs">3 papers</span>
      </div>
    ),
  },
  parameters: {
    layout: "fullscreen",
    msw: { handlers: preferenceHandlers },
  },
  decorators: [
    (Story) => (
      <ToastProvider dismissLabel="Dismiss notification">
        <div className="mx-auto h-[calc(100dvh-3rem)] min-h-80 w-full max-w-[1680px] p-6">
          <Story />
        </div>
      </ToastProvider>
    ),
  ],
} satisfies Meta<typeof PaperCollectionWorkbench>;

export default meta;
type Story = StoryObj<typeof meta>;

async function expectCompactTableSemantics(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  const table = await canvas.findByRole("table");
  await waitFor(() => expect(table).toHaveAttribute("aria-colcount", "3"));
  const headers = within(table).getAllByRole("columnheader");
  await expect(within(table).getAllByRole("row")[0]).toHaveAttribute(
    "aria-rowindex",
    "1",
  );
  await expect(headers).toHaveLength(3);
  await expect(headers.map((header) => header.textContent)).toEqual([
    "Paper thumbnail",
    "Paper",
    "Actions",
  ]);
  await waitFor(() =>
    expect(within(table).getAllByRole("row").slice(1).length).toBeGreaterThan(
      0,
    ),
  );
  const rows = within(table).getAllByRole("row").slice(1);
  await expect(rows[0]).toHaveAttribute("aria-rowindex", "2");
  rows.forEach((row) =>
    expect(within(row).getAllByRole("cell")).toHaveLength(3),
  );
  await expect(
    canvas.queryByRole("checkbox", { name: "Select paper" }),
  ).not.toBeInTheDocument();
  await expect(table.querySelector("[aria-selected]")).toBeNull();
}

export const Library: Story = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(canvasElement.ownerDocument.body);
    const paperLink = await canvas.findByRole("link", {
      name: /Memory as a Controlled Process/,
    });
    await expect(paperLink).toHaveAttribute(
      "href",
      "/reader/00000000-0000-4000-8000-000000000001",
    );
    await expect(
      canvas.getByRole("heading", { name: "Key findings" }),
    ).toBeVisible();
    const paperResize = canvas.getByRole("separator", {
      name: "Resize boundary between Paper and Active reading",
    });
    const initialPaperWidth = Number(paperResize.getAttribute("aria-valuenow"));
    paperResize.focus();
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() =>
      expect(paperResize).toHaveAttribute(
        "aria-valuenow",
        String(initialPaperWidth - 8),
      ),
    );
    const previewResize = canvas.getByRole("separator", {
      name: "Resize paper details",
    });
    await expect(previewResize).toHaveAttribute("aria-valuenow", "512");
    previewResize.focus();
    await expect(previewResize).toHaveFocus();
    fireEvent.keyDown(previewResize, { key: "ArrowRight" });
    await waitFor(() =>
      expect(previewResize).toHaveAttribute("aria-valuenow", "504"),
    );
    const status = canvas.getAllByRole("button", {
      name: /Reading status for/,
    })[0]!;
    await userEvent.click(status);
    await expect(paperLink).toHaveAttribute(
      "href",
      "/reader/00000000-0000-4000-8000-000000000001",
    );
    await userEvent.keyboard("{Escape}");

    const preview = canvas.getByRole("complementary", {
      name: "Paper details",
    });
    await expect(
      within(preview).getByText("10.48550/arXiv.2608.12001"),
    ).toBeVisible();
    await userEvent.click(
      within(preview).getByRole("button", {
        name: /Reading status for.*Memory as a Controlled Process/,
      }),
    );
    await userEvent.click(body.getByRole("menuitem", { name: "Read" }));
    await expect(args.onStatusChange).toHaveBeenCalledWith(
      items[0],
      "completed",
    );
    await userEvent.click(
      within(preview).getByRole("button", {
        name: /Filter by Memory.*Memory as a Controlled Process/,
      }),
    );
    await expect(args.onTagClick).toHaveBeenCalledWith(items[0]!.tags[0]);
    const longTitleLink = canvas.getByRole("link", {
      name: /A deliberately long research paper title/,
    });
    await userEvent.hover(longTitleLink);
    await expect(
      within(preview).getByRole("heading", {
        name: /A deliberately long research paper title/,
      }),
    ).toBeVisible();
    const finalPaperLink = canvas.getByRole("link", {
      name: /When Does Pairing Seeds Reduce Variance/,
    });
    await userEvent.hover(finalPaperLink);
    await expect(
      within(preview).getByRole("heading", {
        name: /When Does Pairing Seeds Reduce Variance/,
      }),
    ).toBeVisible();
    await userEvent.unhover(finalPaperLink);
    await expect(
      within(preview).getByRole("heading", {
        name: /When Does Pairing Seeds Reduce Variance/,
      }),
    ).toBeVisible();
    await expect(finalPaperLink.closest('[role="row"]')).toHaveAttribute(
      "data-current",
      "true",
    );
    await expect(paperLink.closest('[role="row"]')).toHaveAttribute(
      "data-current",
      "false",
    );
    const previewToggle = canvas.getByRole("button", {
      name: "Close paper details",
    });
    await expect(previewToggle).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(previewToggle);
    await expect(previewToggle).toHaveAttribute("aria-pressed", "false");
    await expect(previewToggle).toHaveAccessibleName("Show paper details");
    await expect(previewToggle).toHaveFocus();
    await expect(
      canvas.queryByRole("complementary", { name: "Paper details" }),
    ).not.toBeInTheDocument();
    await userEvent.click(previewToggle);
    await expect(
      canvas.getByRole("complementary", { name: "Paper details" }),
    ).toBeVisible();
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

export const ContainedScrolling: Story = {
  args: {
    items: scrollingItems,
    tableFooter: (
      <p className="text-secondary py-6 text-center text-xs">End of papers</p>
    ),
  },
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const toolbar = canvasElement.querySelector<HTMLElement>(
      "[data-paper-collection-toolbar]",
    );
    const scroller = canvasElement.querySelector<HTMLElement>(
      "[data-paper-collection-scroll]",
    );
    const split = canvasElement.querySelector<HTMLElement>(
      "[data-paper-collection-split]",
    );
    await expect(toolbar).not.toBeNull();
    await expect(scroller).not.toBeNull();
    await expect(split).not.toBeNull();
    if (!toolbar || !scroller || !split) return;

    const toolbarTop = toolbar.getBoundingClientRect().top;
    scroller.scrollTop = scroller.scrollHeight;
    fireEvent.scroll(scroller);
    await waitFor(() => expect(scroller.scrollTop).toBeGreaterThan(0));

    expect(
      Math.abs(toolbar.getBoundingClientRect().top - toolbarTop),
    ).toBeLessThanOrEqual(1);
    expect(getComputedStyle(scroller).overscrollBehaviorY).toBe("contain");
    expect(split.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      split.parentElement!.getBoundingClientRect().bottom + 1,
    );
  },
};

export const Dark: Story = {
  globals: { appearance: "dark" },
};

export const Chinese: Story = {
  globals: { locale: "zh-CN" },
};

export const AdjacentColumnResizing: Story = {
  parameters: {
    msw: { handlers: resizePreferenceHandlers },
    viewport: { defaultViewport: "desktop" },
  },
  play: async ({ canvasElement }) => {
    resizePreferenceRequestCount = 0;
    resizedPreferences = preferences;
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Close paper details" }),
    );
    await waitFor(() => expect(resizePreferenceRequestCount).toBe(1));
    resizePreferenceRequestCount = 0;
    const table = await canvas.findByRole("table");
    const columnHeader = (label: string) => {
      const header = within(table)
        .getAllByRole("columnheader")
        .find((candidate) => candidate.textContent?.trim() === label);
      expect(header).toBeDefined();
      return header!;
    };
    const dragLeft = (separator: HTMLElement, distance: number) => {
      const startX = separator.getBoundingClientRect().x + 8;
      fireEvent.pointerDown(separator, { clientX: startX, pointerId: 1 });
      fireEvent.pointerMove(separator, {
        clientX: startX - distance,
        pointerId: 1,
      });
      fireEvent.pointerUp(separator, {
        clientX: startX - distance,
        pointerId: 1,
      });
    };

    const paper = columnHeader("Paper");
    const readingTime = columnHeader("Active reading");
    const status = columnHeader("Status");
    const paperBoundary = canvas.getByRole("separator", {
      name: "Resize boundary between Paper and Active reading",
    });
    await expect(paperBoundary).toHaveAttribute("aria-valuemin", "232");
    const paperBefore = paper.getBoundingClientRect();
    const readingTimeBefore = readingTime.getBoundingClientRect();
    dragLeft(paperBoundary, 48);
    await waitFor(() => {
      const paperAfter = paper.getBoundingClientRect();
      const readingTimeAfter = readingTime.getBoundingClientRect();
      expect(paperAfter.width).toBeCloseTo(paperBefore.width - 48, 0);
      expect(readingTimeAfter.width).toBeCloseTo(
        readingTimeBefore.width + 48,
        0,
      );
      expect(readingTimeAfter.right).toBeCloseTo(readingTimeBefore.right, 0);
    });
    await waitFor(() => expect(resizePreferenceRequestCount).toBe(1));

    const tags = columnHeader("Tags");
    const statusBoundary = canvas.getByRole("separator", {
      name: "Resize boundary between Status and Tags",
    });
    const statusBeforeSecondDrag = status.getBoundingClientRect();
    const tagsBefore = tags.getBoundingClientRect();
    dragLeft(statusBoundary, 8);
    await waitFor(() => {
      const statusAfter = status.getBoundingClientRect();
      const tagsAfter = tags.getBoundingClientRect();
      expect(statusAfter.width).toBeCloseTo(
        statusBeforeSecondDrag.width - 8,
        0,
      );
      expect(tagsAfter.width).toBeCloseTo(tagsBefore.width + 8, 0);
      expect(tagsAfter.right).toBeCloseTo(tagsBefore.right, 0);
    });
    await waitFor(() => expect(resizePreferenceRequestCount).toBe(2));
    const lastOpened = columnHeader("Last opened");
    await expect(
      lastOpened.querySelector("[data-paper-resize-handle]"),
    ).toBeNull();

    const persistedWidths = Object.fromEntries(
      resizedPreferences.column_widths.map(({ column, width }) => [
        column,
        width,
      ]),
    );
    const persistedStatus = persistedWidths.status;
    const persistedTags = persistedWidths.tags;
    if (persistedStatus === undefined || persistedTags === undefined) {
      throw new Error("Expected Status and Tags widths to be persisted");
    }
    expect(persistedStatus + persistedTags).toBeCloseTo(
      statusBeforeSecondDrag.width + tagsBefore.width,
      0,
    );
  },
};

export const ColumnConfiguration: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Configure columns" }),
    );
    await expect(
      await body.findByRole("heading", { name: "Visible columns" }),
    ).toBeVisible();
    await expect(body.getAllByRole("checkbox")).toHaveLength(8);
    await expect(
      body.getByRole("button", { name: "Reset all widths" }),
    ).toBeVisible();
  },
};

export const Narrow: Story = {
  parameters: { viewport: { defaultViewport: "tablet" } },
};

export const Mobile: Story = {
  args: {
    leading: () => <input aria-label="Select paper" type="checkbox" />,
  },
  parameters: { viewport: { defaultViewport: "mobile" } },
  play: async ({ canvasElement }) => expectCompactTableSemantics(canvasElement),
};

export const SmallMobile: Story = {
  args: {
    leading: () => <input aria-label="Select paper" type="checkbox" />,
  },
  parameters: { viewport: { defaultViewport: "smallMobile" } },
  play: async ({ canvasElement }) => expectCompactTableSemantics(canvasElement),
};

const oldPreviewUrl =
  "data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%201%201%22%3E%3Cpath%20fill=%22%23ececea%22%20d=%22M0%200h1v1H0z%22/%3E%3C/svg%3E";
const refreshedPreviewUrl =
  "data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%201%201%22%3E%3Cpath%20fill=%22%23d7d7d2%22%20d=%22M0%200h1v1H0z%22/%3E%3C/svg%3E";

function PreviewUrlRefreshHarness() {
  const [previewUrl, setPreviewUrl] = React.useState(oldPreviewUrl);
  return (
    <>
      <button onClick={() => setPreviewUrl(refreshedPreviewUrl)} type="button">
        Refresh signed URL
      </button>
      <PaperCollectionWorkbench
        items={[{ ...items[0]!, previewUrl }]}
        toolbar={<span>Preview refresh</span>}
      />
    </>
  );
}

export const PreviewUrlRefresh: Story = {
  render: () => <PreviewUrlRefreshHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(
      () =>
        expect(
          canvasElement.querySelectorAll(`img[src="${oldPreviewUrl}"]`).length,
        ).toBeGreaterThanOrEqual(2),
      { timeout: 5000 },
    );
    const oldImages = Array.from(
      canvasElement.querySelectorAll<HTMLImageElement>(
        `img[src="${oldPreviewUrl}"]`,
      ),
    );
    oldImages.forEach((image) => fireEvent.error(image));
    await waitFor(() =>
      expect(
        canvasElement.querySelectorAll("[data-paper-image-fallback]").length,
      ).toBeGreaterThanOrEqual(oldImages.length),
    );

    await userEvent.click(
      canvas.getByRole("button", { name: "Refresh signed URL" }),
    );
    await waitFor(() =>
      expect(
        canvasElement.querySelectorAll(`img[src="${refreshedPreviewUrl}"]`),
      ).toHaveLength(oldImages.length),
    );
  },
};

export const QueuedPreferenceUpdates: Story = {
  parameters: { msw: { handlers: queuedPreferenceHandlers } },
  play: async ({ canvasElement }) => {
    queuedPreferenceRequestCount = 0;
    queuedPersistedPreferences = {
      ...preferences,
      visible_columns: [...preferences.visible_columns],
    };
    const canvas = within(canvasElement);
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Configure columns" }),
    );
    await userEvent.click(await body.findByRole("checkbox", { name: "DOI" }));
    await userEvent.click(body.getByRole("checkbox", { name: "Authors" }));

    await waitFor(() => expect(queuedPreferenceRequestCount).toBe(2));
    await waitFor(() =>
      expect(queuedPersistedPreferences.visible_columns).toEqual([
        "reading_time",
        "status",
        "tags",
        "publication",
        "last_opened",
        "doi",
      ]),
    );
    await expect(body.getByRole("checkbox", { name: "DOI" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(
      body.getByRole("checkbox", { name: "Authors" }),
    ).toHaveAttribute("aria-checked", "false");
    await userEvent.keyboard("{Escape}");
  },
};

export const KeyboardColumnReordering: Story = {
  parameters: { msw: { handlers: queuedPreferenceHandlers } },
  play: async ({ canvasElement }) => {
    queuedPreferenceRequestCount = 0;
    queuedPersistedPreferences = {
      ...preferences,
      visible_columns: [...preferences.visible_columns],
    };
    const canvas = within(canvasElement);
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Configure columns" }),
    );

    await expect(
      body.getByRole("button", { name: "Move Active reading up" }),
    ).toBeDisabled();
    await expect(
      body.getByRole("button", { name: "Move Last opened down" }),
    ).toBeDisabled();

    const moveAuthorsUp = body.getByRole("button", {
      name: "Move Authors up",
    });
    moveAuthorsUp.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(
        body.getByRole("button", { name: "Move Authors up" }),
      ).toHaveFocus(),
    );
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(
        body.getByRole("button", { name: "Move Authors up" }),
      ).toHaveFocus(),
    );
    await userEvent.keyboard("{Enter}");

    await waitFor(() => expect(queuedPreferenceRequestCount).toBe(3));
    await waitFor(() =>
      expect(queuedPersistedPreferences.visible_columns).toEqual([
        "authors",
        "reading_time",
        "status",
        "tags",
        "publication",
        "last_opened",
      ]),
    );
    await expect(
      body.getByRole("button", { name: "Move Authors up" }),
    ).toBeDisabled();
    await expect(
      body.getByRole("heading", { name: "Visible columns" }),
    ).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        body.queryByRole("heading", { name: "Visible columns" }),
      ).toBeNull(),
    );
  },
};

export const FailedPreferenceUpdateBeforeInitialQuery: Story = {
  parameters: { msw: { handlers: failingPreferenceHandlers } },
  play: async ({ canvasElement }) => {
    failedPreferenceRequestCount = 0;
    const canvas = within(canvasElement);
    const body = within(canvasElement.ownerDocument.body);
    const trigger = await canvas.findByRole("button", {
      name: "Configure columns",
    });
    await userEvent.click(trigger);
    const doi = await body.findByRole("checkbox", { name: "DOI" });
    await userEvent.click(doi);
    await userEvent.click(body.getByRole("checkbox", { name: "Authors" }));
    await waitFor(() => expect(failedPreferenceRequestCount).toBe(2));
    await body.findAllByText("Paper list preferences could not be saved.");
    await waitFor(() =>
      expect(body.getByRole("checkbox", { name: "DOI" })).toHaveAttribute(
        "aria-checked",
        "false",
      ),
    );
    await expect(
      body.getByRole("checkbox", { name: "Authors" }),
    ).toHaveAttribute("aria-checked", "true");
    await expect(
      body.getByRole("button", { name: "Move Active reading up" }),
    ).toBeDisabled();
    await userEvent.click(trigger);
    await waitFor(() =>
      expect(
        body.queryByRole("heading", { name: "Visible columns" }),
      ).toBeNull(),
    );
  },
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
