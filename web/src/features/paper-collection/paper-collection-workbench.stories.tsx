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
import type { PaperListPreferences } from "./api";

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
    addedAt: "Aug 20, 2026",
    authors: ["Eric Hanchen Jiang", "Zhi Zhang", "Yuchen Wu"],
    doi: "10.48550/arXiv.2608.12001",
    href: "/reader/00000000-0000-4000-8000-000000000001" as Route,
    id: "00000000-0000-4000-8000-000000000001",
    inLibrary: true,
    keywords: ["memory", "agents", "retrieval"],
    lastOpened: "Today, 14:32",
    publication: "arXiv · 2026",
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
        <div className="mx-auto w-full max-w-[1680px] p-6">
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
      within(preview).getByRole("button", { name: "Memory" }),
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
    await userEvent.unhover(longTitleLink);
    await expect(
      within(preview).getByRole("heading", {
        name: /Memory as a Controlled Process/,
      }),
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

const oldPreviewUrl = "https://preview.example/old-signed-url.png";
const refreshedPreviewUrl = "https://preview.example/new-signed-url.png";

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
    await userEvent.click(
      await body.findByRole("menuitemcheckbox", { name: "DOI" }),
    );
    await userEvent.click(
      body.getByRole("menuitemcheckbox", { name: "Authors" }),
    );

    await waitFor(() => expect(queuedPreferenceRequestCount).toBe(2));
    await waitFor(() =>
      expect(queuedPersistedPreferences.visible_columns).toEqual([
        "status",
        "tags",
        "publication",
        "last_opened",
        "doi",
      ]),
    );
    await expect(
      body.getByRole("menuitemcheckbox", { name: "DOI" }),
    ).toHaveAttribute("aria-checked", "true");
    await expect(
      body.getByRole("menuitemcheckbox", { name: "Authors" }),
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
      body.getByRole("menuitem", { name: "Move Status up" }),
    ).toHaveAttribute("aria-disabled", "true");
    await expect(
      body.getByRole("menuitem", { name: "Move Last opened down" }),
    ).toHaveAttribute("aria-disabled", "true");

    body.getByRole("menuitemcheckbox", { name: "Authors" }).focus();
    await userEvent.keyboard("{ArrowDown}");
    const moveAuthorsUp = body.getByRole("menuitem", {
      name: "Move Authors up",
    });
    await expect(moveAuthorsUp).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(
        body.getByRole("menuitem", { name: "Move Authors up" }),
      ).toHaveFocus(),
    );
    await userEvent.keyboard("{Enter}");

    await waitFor(() => expect(queuedPreferenceRequestCount).toBe(2));
    await waitFor(() =>
      expect(queuedPersistedPreferences.visible_columns).toEqual([
        "authors",
        "status",
        "tags",
        "publication",
        "last_opened",
      ]),
    );
    await expect(
      body.getByRole("menuitem", { name: "Move Authors up" }),
    ).toHaveAttribute("aria-disabled", "true");
    await expect(body.getByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(body.queryByRole("menu")).toBeNull());
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
    const doi = await body.findByRole("menuitemcheckbox", { name: "DOI" });
    await userEvent.click(doi);
    await userEvent.click(
      body.getByRole("menuitemcheckbox", { name: "Authors" }),
    );
    await waitFor(() => expect(failedPreferenceRequestCount).toBe(2));
    await body.findAllByText("Paper list preferences could not be saved.");
    await waitFor(() =>
      expect(
        body.getByRole("menuitemcheckbox", { name: "DOI" }),
      ).toHaveAttribute("aria-checked", "false"),
    );
    await expect(
      body.getByRole("menuitemcheckbox", { name: "Authors" }),
    ).toHaveAttribute("aria-checked", "true");
    await expect(
      body.getByRole("menuitem", { name: "Move Status up" }),
    ).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(body.getByRole("menuitem", { name: "Done" }));
    await waitFor(() => expect(body.queryByRole("menu")).toBeNull());
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
