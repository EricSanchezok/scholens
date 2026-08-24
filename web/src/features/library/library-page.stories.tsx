import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { getRouter } from "@storybook/nextjs-vite/navigation.mock";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";

import { authHandlers, actor } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import {
  expectLayeredKeyboardFocus,
  expectStableFocusPerimeter,
  focusWithKeyboard,
  readFocusVisual,
} from "@/components/ui/focus-contract.story-test";
import { resetRefreshForTests } from "@/lib/api";
import { libraryHandlers } from "./api/handlers";
import { libraryLongTitlePapers } from "./api/fixtures";
import { LibraryWorkspace } from "./library-page";

const meta = {
  title: "Features/Library/Papers",
  component: LibraryWorkspace,
  args: { actor },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
  loaders: [
    async () => {
      resetRefreshForTests();
      window.history.replaceState({}, "", "/library");
      window.sessionStorage.clear();
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.populated] },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof LibraryWorkspace>;

export default meta;
type Story = StoryObj<typeof meta>;

function resolveColor(value: string, property: "backgroundColor" | "color") {
  const reference = document.createElement("span");
  reference.style[property] = value;
  document.body.append(reference);
  const resolved = getComputedStyle(reference)[property];
  reference.remove();
  return resolved;
}

async function expectSingleLineToolbar(canvasElement: HTMLElement) {
  const toolbar = canvasElement.querySelector<HTMLElement>(
    "[data-collection-toolbar]",
  );
  await expect(toolbar).not.toBeNull();
  if (!toolbar) return;
  const search = toolbar.querySelector<HTMLElement>('input[type="search"]');
  const controls = Array.from(
    toolbar.querySelectorAll<HTMLElement>(
      "[data-collection-toolbar-controls] > button, [data-collection-toolbar-controls] > div > button",
    ),
  ).filter((control) => control.getClientRects().length > 0);
  await expect(search).not.toBeNull();
  if (!search) return;
  const boxes = [search, ...controls].map((element) =>
    element.getBoundingClientRect(),
  );
  await expect(
    Math.max(...boxes.map((box) => box.top)) -
      Math.min(...boxes.map((box) => box.top)),
  ).toBeLessThanOrEqual(1);
  await expect(toolbar.scrollWidth).toBeLessThanOrEqual(toolbar.clientWidth);
}

export const Populated: Story = {
  globals: { viewport: { value: "desktop", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", { name: "Library" }),
    ).toBeVisible();
    const heading = canvas.getByRole("heading", { name: "Library" });
    const workbenchHeader = heading.closest("header");
    await expect(workbenchHeader).not.toBeNull();
    const search = await canvas.findByRole("searchbox", {
      name: "Search papers",
    });
    if (workbenchHeader) {
      await expect(
        Math.round(
          search.getBoundingClientRect().top -
            workbenchHeader.getBoundingClientRect().bottom,
        ),
      ).toBe(16);
    }
    const titles = await canvas.findAllByText("Attention Is All You Need");
    await expect(
      titles.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(canvas.getByRole("table")).toBeVisible();
    const tableSurface = canvas.getByRole("table");
    const splitSurface = tableSurface.closest<HTMLElement>(
      "[data-paper-collection-split]",
    );
    await expect(splitSurface).not.toBeNull();
    await expect(getComputedStyle(tableSurface).borderLeftWidth).toBe("0px");
    await expect(getComputedStyle(tableSurface).borderTopWidth).toBe("0px");
    await expect(getComputedStyle(splitSurface!).borderTopWidth).toBe("1px");
    await expect(getComputedStyle(tableSurface).borderRadius).toBe("0px");
    const pageLayout = canvasElement.querySelector<HTMLElement>(
      "[data-paper-collection-page-layout]",
    );
    await expect(pageLayout).not.toBeNull();
    const preview = await canvas.findByRole("complementary", {
      name: "Paper details",
    });
    const layoutBox = pageLayout!.getBoundingClientRect();
    const previewBox = preview.getBoundingClientRect();
    await expect(Math.abs(previewBox.top - layoutBox.top)).toBeLessThanOrEqual(
      1,
    );
    await expect(
      Math.abs(previewBox.bottom - layoutBox.bottom),
    ).toBeLessThanOrEqual(1);
    await expect(search).toHaveClass("rounded-full");
    await expect(
      canvas
        .getAllByText("Transformers")
        .some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(
      canvasElement.querySelectorAll("[data-paper-thumbnail]").length,
    ).toBeGreaterThan(0);
    const continuedTitles = await canvas.findAllByText(
      "Follow-up reading 1: Attention Is All You Need",
    );
    await expect(
      continuedTitles.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(
      canvas.queryByRole("button", { name: "Previous" }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("button", { name: "Next" }),
    ).not.toBeInTheDocument();

    const focusSearch = canvas.getByRole("searchbox", {
      name: "Search papers",
    });
    const searchSurface = focusSearch.closest<HTMLElement>(
      "[data-focus-surface]",
    );
    await expect(searchSurface).not.toBeNull();
    const restingInput = readFocusVisual(focusSearch);
    const restingSurface = readFocusVisual(searchSurface!);
    await focusWithKeyboard(focusSearch);
    await expectStableFocusPerimeter({
      element: focusSearch,
      resting: restingInput,
    });
    await expectLayeredKeyboardFocus({
      element: searchSurface!,
      resting: restingSurface,
    });
  },
};

export const HybridSearchResults: Story = {
  parameters: {
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: "/library?q=code%20world",
        pathname: "/library",
        query: { q: "code world" },
      },
    },
  },
  loaders: [
    async () => {
      window.history.replaceState({}, "", "/library?q=code%20world");
      return {};
    },
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("link", {
        name: /CWM: An Open-Weights LLM for Code Generation with World Models/,
      }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("searchbox", { name: "Search papers" }),
    ).toHaveValue("code world");
  },
};

export const Mobile390HybridSearchResults: Story = {
  ...HybridSearchResults,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Empty: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.empty] },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText("No papers found"),
    ).toBeVisible();
  },
};

export const Loading: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.loading] },
  },
};

export const Error: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.error] },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText(
        "Papers could not be loaded",
        {},
        { timeout: 3_000 },
      ),
    ).toBeVisible();
  },
};

export const MultiSelect: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table");
    const firstRow = within(table)
      .getByRole("link", { name: "Attention Is All You Need" })
      .closest<HTMLElement>('[role="row"]');
    await expect(firstRow).not.toBeNull();
    if (!firstRow) return;
    const first = within(firstRow).getByRole("checkbox", {
      name: "Select Attention Is All You Need",
    });
    await userEvent.hover(firstRow);
    await userEvent.click(first);
    const second = canvas.getByRole("checkbox", {
      name: /Select Retrieval-Augmented Generation/,
    });
    await fireEvent.click(second);
    const toolbar = canvas
      .getAllByRole("toolbar", { name: "Paper selection actions" })
      .find((candidate) => candidate.getClientRects().length > 0);
    await expect(toolbar).toBeDefined();
    if (!toolbar) return;
    await expect(within(toolbar).getByText("2 papers selected")).toBeVisible();
    await expect(
      within(toolbar).getByRole("button", { name: "Remove from library" }),
    ).toBeVisible();
    await expect(
      within(toolbar).getByRole("button", {
        name: "Add to project · Not available yet",
      }),
    ).toBeDisabled();
    await userEvent.click(
      within(toolbar).getByRole("button", { name: "Edit tags" }),
    );
    await expect(
      await within(document.body).findByRole("heading", { name: "Edit tags" }),
    ).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await expect(
      toolbar.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  },
};

export const Processing: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...libraryHandlers.processing],
    },
  },
  play: async ({ canvasElement }) => {
    const copies = await within(canvasElement).findAllByText("Reading PDF");
    await expect(
      copies.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
  },
};

export const FailedWithRetry: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.failed] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const copies = await canvas.findAllByText(
      "The source PDF is no longer available.",
    );
    await expect(
      copies.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(canvas.getByRole("button", { name: "Retry" })).toBeVisible();
  },
};

export const AddPapers: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const openButton = await canvas.findByRole("button", {
      name: "Add papers",
    });
    await expect(getComputedStyle(openButton).backgroundColor).toBe(
      resolveColor("var(--color-action-primary)", "backgroundColor"),
    );
    await expect(getComputedStyle(openButton).color).toBe(
      resolveColor("var(--color-action-primary-foreground)", "color"),
    );
    await userEvent.click(openButton);
    const body = within(canvasElement.ownerDocument.body);
    const dialog = await body.findByRole("dialog");
    const overlay = document.querySelector<HTMLElement>(
      '[data-slot="dialog-overlay"]',
    );
    await expect(
      await body.findByRole("heading", { name: "Add papers" }),
    ).toBeVisible();
    await expect(body.getByText("PDF files")).toBeVisible();
    await expect(body.getByText("DOI, arXiv, or PDF URL")).toBeVisible();
    await expect(getComputedStyle(dialog).backgroundColor).toBe(
      resolveColor("var(--color-bg-elevated)", "backgroundColor"),
    );
    await expect(getComputedStyle(dialog).borderTopStyle).toBe("solid");
    await expect(getComputedStyle(dialog).borderTopColor).toBe(
      resolveColor("var(--color-border-default)", "color"),
    );
    await expect(overlay).not.toBeNull();
    await expect(getComputedStyle(overlay!).backgroundColor).toBe(
      resolveColor("var(--color-overlay-backdrop)", "backgroundColor"),
    );
  },
};

export const AddPapersDuplicateSelection: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(
      await within(canvasElement).findByRole("button", { name: "Add papers" }),
    );
    const body = within(document.body);
    const input = await body.findByLabelText("Choose PDFs");
    const duplicate = new File(["%PDF-1.7 same content"], "same-paper.pdf", {
      type: "application/pdf",
    });

    await userEvent.upload(input, [duplicate, duplicate]);

    await expect(
      await body.findByText(
        "1 duplicate PDF was ignored. The same content only needs to be uploaded once.",
      ),
    ).toBeVisible();
    await expect(body.getAllByText("same-paper.pdf")).toHaveLength(1);
    await expect(
      body.getByRole("button", { name: "Upload 1 file" }),
    ).toBeVisible();
  },
};

export const AddPapersOpenAlexRequired: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...libraryHandlers.openAlexRequired],
    },
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      await within(canvasElement).findByRole("button", { name: "Add papers" }),
    );
    const body = within(document.body);
    await userEvent.type(
      await body.findByPlaceholderText("10.1000/example"),
      "10.1038/example",
    );
    await userEvent.click(body.getByRole("button", { name: "Add source" }));
    await expect(
      await body.findByText(/Connect your OpenAlex API key/),
    ).toBeVisible();
    await expect(body.getByDisplayValue("10.1038/example")).toBeVisible();
    await userEvent.click(
      body.getByRole("button", { name: "Connect OpenAlex" }),
    );
    if (window.matchMedia("(min-width: 64rem)").matches) {
      await expect(getRouter().replace).toHaveBeenCalledWith(
        expect.stringContaining("settings=connections"),
        { scroll: false },
      );
    } else {
      await expect(getRouter().push).toHaveBeenCalledWith(
        expect.stringContaining("/me/connections?returnTo="),
        { scroll: false },
      );
    }
  },
};

export const Mobile320AddPapersOpenAlexRequired: Story = {
  ...AddPapersOpenAlexRequired,
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};

export const Mobile390AddPapersOpenAlexRequired: Story = {
  ...AddPapersOpenAlexRequired,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const DarkChineseAddPapersOpenAlexRequired: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...libraryHandlers.openAlexRequired],
    },
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      await within(canvasElement).findByRole("button", { name: "添加论文" }),
    );
    const body = within(document.body);
    await userEvent.type(
      await body.findByPlaceholderText("10.1000/example"),
      "10.1038/example",
    );
    await userEvent.click(body.getByRole("button", { name: "添加来源" }));
    await expect(
      await body.findByText(/需要先连接你自己的 OpenAlex API Key/),
    ).toBeVisible();
    await expect(
      body.getByRole("button", { name: "连接 OpenAlex" }),
    ).toBeVisible();
  },
};

export const Mobile390: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expectSingleLineToolbar(canvasElement);
    const titles = await canvas.findAllByText("Attention Is All You Need");
    await expect(
      titles.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(canvas.getByRole("table")).toBeInTheDocument();
    await expect(
      canvas.getByRole("button", { name: "Add papers" }),
    ).toBeVisible();
    const card = titles
      .find(
        (element) => element.closest('[role="row"]')?.getClientRects().length,
      )
      ?.closest('[role="row"]');
    await expect(card).not.toBeNull();
    if (!card) return;
    await expect(
      within(card as HTMLElement)
        .getAllByText(/Ashish Vaswani/)
        .some((element) => element.getClientRects().length > 0),
    ).toBe(true);
  },
};

export const Mobile320LongTitles: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.longTitles] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expectSingleLineToolbar(canvasElement);
    const titleText = libraryLongTitlePapers[0]!.document.title!;
    const title = (await canvas.findAllByText(titleText)).find(
      (candidate) => candidate.closest('[role="row"]')?.getClientRects().length,
    );
    await expect(title).toBeDefined();
    if (!title) return;
    const row = title.closest('[role="row"]');
    await expect(row).not.toBeNull();
    await expect(getComputedStyle(title).webkitLineClamp).toBe("2");
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};

export const Mobile430Filters: Story = {
  globals: { viewport: { value: "largeMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expectSingleLineToolbar(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Tags" }));
    const body = within(canvasElement.ownerDocument.body);
    const dialog = await body.findByRole("dialog");
    await expect(dialog).toHaveAttribute("data-state", "open");
    await expect(dialog).toHaveTextContent("Tags");
  },
};

export const Mobile320MultiSelect: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", {
        name: "Actions for Attention Is All You Need",
      }),
    );
    await userEvent.click(
      await within(document.body).findByRole("menuitem", {
        name: "Select paper",
      }),
    );
    let toolbar: HTMLElement | undefined;
    await waitFor(() => {
      toolbar = canvas
        .getAllByRole("toolbar", { name: "Paper selection actions" })
        .find((candidate) => candidate.getClientRects().length > 0);
      expect(toolbar).toBeDefined();
    });
    if (!toolbar) return;
    await expect(within(toolbar).getByText("1 paper selected")).toBeVisible();
    await expect(
      within(toolbar).getByRole("button", { name: "Actions" }),
    ).toBeVisible();
  },
};

export const Mobile390AddPapers: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      await within(canvasElement).findByRole("button", { name: "Add papers" }),
    );
    await expect(
      await within(document.body).findByRole("heading", { name: "Add papers" }),
    ).toBeVisible();
  },
};

export const Mobile390Processing: Story = {
  ...Processing,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Mobile390FailedWithRetry: Story = {
  ...FailedWithRetry,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Mobile390Empty: Story = {
  ...Empty,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Mobile430Loading: Story = {
  ...Loading,
  globals: { viewport: { value: "largeMobile", isRotated: false } },
};

export const Mobile320Error: Story = {
  ...Error,
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};
