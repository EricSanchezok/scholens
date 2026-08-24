import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { http, HttpResponse } from "msw";
import {
  expect,
  fireEvent,
  fn,
  userEvent,
  waitFor,
  within,
} from "storybook/test";

import {
  expectLayeredKeyboardFocus,
  expectStableFocusPerimeter,
  focusWithKeyboard,
  readFocusVisual,
} from "@/components/ui/focus-contract.story-test";
import { ResearchComposer } from "./research-composer";

const api = "http://127.0.0.1:7301/api/v1";
const contextCatalogHandlers = [
  http.get(`${api}/library/papers`, ({ request }) => {
    const query = new URL(request.url).searchParams.get("q");
    return HttpResponse.json({
      items:
        query === "remote"
          ? [
              {
                document: {
                  authors: ["Catalog Author"],
                  document_id: "30000000-0000-4000-8000-000000000099",
                  journal: "Catalog Journal",
                  original_filename: "remote-catalog.pdf",
                  title: "Remote catalog paper",
                },
                entry_type: "paper",
                metadata_overrides: { title: null },
              },
            ]
          : [],
      next_cursor: null,
      previous_cursor: null,
      total_count: query === "remote" ? 1 : 0,
    });
  }),
  http.get(`${api}/projects`, () =>
    HttpResponse.json({ items: [], next_cursor: null, total_count: 0 }),
  ),
];

const meta = {
  title: "Conversation/ResearchComposer",
  component: ResearchComposer,
  args: {
    context: { kind: "library" },
    surface: "workspace",
    onContextChange: fn(),
    onReasoningLevelChange: fn(),
    onStop: fn(),
    onSubmit: fn(async () => undefined),
    papers: [],
    projects: [],
    reasoningLevel: "standard",
  },
  decorators: [
    (Story) => (
      <main className="flex min-h-dvh items-end p-3">
        <Story />
      </main>
    ),
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: contextCatalogHandlers },
  },
} satisfies Meta<typeof ResearchComposer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Desktop: Story = {};

export const Mobile: Story = {
  globals: { viewport: { value: "mobile" } },
};

export const Streaming: Story = {
  args: { busy: true },
};

export const ContextPanelSelection: Story = {
  args: {
    context: {
      kind: "selection",
      document_ids: ["paper-1"],
      project_ids: [],
    },
    onTurnContextClear: fn(),
    surface: "context-panel",
    turnContextLabel: "Page 4 selection",
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-dvh items-end justify-end p-3">
        <div className="w-[23rem] max-w-full">
          <Story />
        </div>
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const textbox = canvas.getByRole("textbox");
    const composer = textbox.closest("form");
    await expect(composer).not.toBeNull();
    await expect(composer).toHaveAttribute("data-expanded", "true");
    const restingBorder = getComputedStyle(composer!).borderTopColor;
    await expect(restingBorder).not.toBe("transparent");
    const restingTextbox = readFocusVisual(textbox);
    const restingComposer = readFocusVisual(composer!);
    await focusWithKeyboard(textbox);
    await expect(composer).toHaveAttribute("data-focus-surface");
    await expectStableFocusPerimeter({
      element: textbox,
      resting: restingTextbox,
    });
    await expectLayeredKeyboardFocus({
      element: composer!,
      resting: restingComposer,
    });
  },
};

export const ContextPanelCompact: Story = {
  args: {
    context: {
      kind: "selection",
      document_ids: ["paper-1"],
      project_ids: [],
    },
    surface: "context-panel",
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-dvh items-end justify-end p-3">
        <div className="w-[23rem] max-w-full">
          <Story />
        </div>
      </div>
    ),
  ],
  globals: { viewport: { value: "desktop" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const textbox = canvas.getByRole("textbox");
    const composer = textbox.closest("form");
    await expect(composer).not.toBeNull();
    if (!composer) return;
    await expect(composer).toHaveAttribute("data-expanded", "false");
    await expect(composer.getBoundingClientRect().height).toBeLessThan(64);
    await expect(
      Number.parseFloat(getComputedStyle(composer).borderRadius),
    ).toBeGreaterThanOrEqual(999);
    await userEvent.click(
      canvas.getByRole("button", { name: "Reasoning strength: Standard" }),
    );
    const page = within(canvasElement.ownerDocument.body);
    await expect(page.getByText("Fast, balanced reasoning")).toBeVisible();
    await expect(page.getByText("More thorough reasoning")).toBeVisible();
    await userEvent.keyboard("{Escape}");
  },
};

export const ContextPanelVisualWrapExpansion: Story = {
  args: {
    context: {
      kind: "selection",
      document_ids: ["paper-1"],
      project_ids: [],
    },
    surface: "context-panel",
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-dvh items-end justify-end p-3">
        <div
          className="w-[23rem] max-w-full"
          data-composer-story-width="compact"
        >
          <Story />
        </div>
      </div>
    ),
  ],
  globals: { viewport: { value: "desktop" } },
  play: async ({ canvasElement }) => {
    const textbox = within(canvasElement).getByRole("textbox");
    const composer = textbox.closest("form");
    await expect(composer).not.toBeNull();
    if (!composer) return;

    const restingBounds = composer.getBoundingClientRect();
    const frame = composer.closest<HTMLElement>("[data-composer-story-width]");
    await expect(frame).not.toBeNull();
    if (!frame) return;

    const wrappedWithoutLineBreak = "这是一段测试文字".repeat(3);
    await expect(wrappedWithoutLineBreak.length).toBeLessThan(88);
    await fireEvent.change(textbox, {
      target: { value: wrappedWithoutLineBreak },
    });
    await waitFor(() =>
      expect(composer).toHaveAttribute("data-expanded", "true"),
    );
    await waitFor(() =>
      expect(
        Number.parseFloat(getComputedStyle(composer).borderRadius),
      ).toBeCloseTo(24, 0),
    );
    const expandedBounds = composer.getBoundingClientRect();
    await expect(Math.round(expandedBounds.bottom)).toBe(
      Math.round(restingBounds.bottom),
    );
    await expect(expandedBounds.top).toBeLessThan(restingBounds.top);

    frame.style.width = "48rem";
    await waitFor(() =>
      expect(composer).toHaveAttribute("data-expanded", "false"),
    );
    frame.style.width = "23rem";
    await waitFor(() =>
      expect(composer).toHaveAttribute("data-expanded", "true"),
    );

    await fireEvent.change(textbox, { target: { value: "短问题" } });
    await waitFor(() =>
      expect(composer).toHaveAttribute("data-expanded", "false"),
    );
    await waitFor(() =>
      expect(
        Number.parseFloat(getComputedStyle(composer).borderRadius),
      ).toBeGreaterThanOrEqual(999),
    );
    const collapsedBounds = composer.getBoundingClientRect();
    await expect(Math.round(collapsedBounds.bottom)).toBe(
      Math.round(restingBounds.bottom),
    );
    await expect(collapsedBounds.height).toBeLessThan(expandedBounds.height);
  },
};

export const ContextPanelMobileVisualWrapExpansion: Story = {
  ...ContextPanelVisualWrapExpansion,
  globals: { viewport: { value: "mobile" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const textbox = canvas.getByRole("textbox") as HTMLTextAreaElement;
    const composer = textbox.closest("form");
    await expect(composer).not.toBeNull();
    if (!composer) return;

    const restingBounds = composer.getBoundingClientRect();
    await fireEvent.change(textbox, {
      target: { value: "这是一段测试文字".repeat(6) },
    });
    await waitFor(() =>
      expect(composer).toHaveAttribute("data-expanded", "true"),
    );
    await expect(
      Number.parseFloat(getComputedStyle(composer).borderRadius),
    ).toBeCloseTo(24, 0);
    await expect(Math.round(composer.getBoundingClientRect().bottom)).toBe(
      Math.round(restingBounds.bottom),
    );
    await expect(
      canvas.queryByRole("button", {
        name: "Reasoning strength: Standard",
      }),
    ).toBeNull();

    await fireEvent.change(textbox, {
      target: {
        value: "这是用于验证输入框达到最大高度后只在内部滚动的长文本。".repeat(
          30,
        ),
      },
    });
    await waitFor(() =>
      expect(textbox.scrollHeight).toBeGreaterThan(textbox.clientHeight),
    );
    await expect(getComputedStyle(textbox).overflowY).toBe("auto");
    await expect(Math.round(composer.getBoundingClientRect().bottom)).toBe(
      Math.round(restingBounds.bottom),
    );

    await fireEvent.change(textbox, { target: { value: "Short question" } });
    await waitFor(() =>
      expect(composer).toHaveAttribute("data-expanded", "false"),
    );
    await expect(
      Number.parseFloat(getComputedStyle(composer).borderRadius),
    ).toBeGreaterThanOrEqual(999);
  },
};

export const ContextPanelMobileHidesReasoningMenu: Story = {
  args: { surface: "context-panel" },
  decorators: [
    (Story) => (
      <div className="flex min-h-dvh items-end p-3">
        <Story />
      </div>
    ),
  ],
  globals: { viewport: { value: "mobile" } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).queryByRole("button", {
        name: "Reasoning strength: Standard",
      }),
    ).toBeNull();
  },
};

export const ContextPanelScopeEditable: Story = {
  args: {
    context: {
      kind: "selection",
      document_ids: [],
      project_ids: [],
    },
    surface: "context-panel",
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-dvh items-end justify-end p-3">
        <div className="w-[23rem] max-w-full">
          <Story />
        </div>
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const trigger = canvas.getByRole("button", {
      name: "Research scope: Select scope",
    });
    await userEvent.click(trigger);
    await expect(
      body.getByRole("heading", { name: "Add context" }),
    ).toBeVisible();
    await expect(body.getByText("Entire library")).toBeVisible();
    await userEvent.click(body.getByRole("button", { name: "Done" }));
    await expect(
      body.queryByRole("heading", { name: "Add context" }),
    ).not.toBeInTheDocument();
    await fireEvent.keyDown(canvas.getByRole("textbox"), { key: "@" });
    await expect(
      body.getByRole("heading", { name: "Add context" }),
    ).toBeVisible();
  },
};

export const ContextPanelServerSearch: Story = {
  args: {
    context: {
      kind: "selection",
      document_ids: [],
      project_ids: [],
    },
    surface: "context-panel",
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-dvh items-end justify-end p-3">
        <div className="w-[23rem] max-w-full">
          <Story />
        </div>
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(
      canvas.getByRole("button", {
        name: "Research scope: Select scope",
      }),
    );
    await userEvent.type(body.getByRole("searchbox"), "remote");
    await expect(await body.findByText("Remote catalog paper")).toBeVisible();
  },
};

export const ContextPanelImeCandidateConfirmation: Story = {
  args: {
    onSubmit: fn(async () => undefined),
    surface: "context-panel",
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-dvh items-end justify-end p-3">
        <div className="w-[23rem] max-w-full">
          <Story />
        </div>
      </div>
    ),
  ],
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const composer = canvas.getByRole("textbox");
    await fireEvent.compositionStart(composer);
    await fireEvent.change(composer, { target: { value: "继续研究" } });
    await waitFor(() =>
      expect(
        canvas.getByRole("button", { name: "Ask Scholens" }),
      ).toBeEnabled(),
    );

    await fireEvent.keyDown(composer, {
      code: "Enter",
      isComposing: true,
      key: "Enter",
      keyCode: 229,
    });
    await expect(args.onSubmit).not.toHaveBeenCalled();

    await fireEvent.compositionEnd(composer, { data: "继续研究" });
    await fireEvent.keyDown(composer, { code: "Enter", key: "Enter" });
    await waitFor(() => expect(args.onSubmit).toHaveBeenCalledWith("继续研究"));
  },
};

export const ContextPanelSelectionDark: Story = {
  ...ContextPanelSelection,
  globals: { appearance: "dark" },
};
