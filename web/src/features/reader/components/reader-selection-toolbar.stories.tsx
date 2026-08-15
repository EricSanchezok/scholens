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

async function expectOpaqueFloatingSurface(
  canvasElement: HTMLElement,
  surfaceName: "actions" | "palette",
) {
  const surface = canvasElement.querySelector<HTMLElement>(
    `[data-reader-selection-toolbar-surface="${surfaceName}"]`,
  );
  const reference = canvasElement.querySelector<HTMLElement>(
    "[data-elevated-surface-reference]",
  );
  await expect(surface).not.toBeNull();
  await expect(reference).not.toBeNull();
  await expect(getComputedStyle(surface!).backgroundColor).toBe(
    getComputedStyle(reference!).backgroundColor,
  );
  await expect(getComputedStyle(surface!).isolation).toBe("isolate");
  await expect(getComputedStyle(surface!).opacity).toBe("1");
}

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
      personal: "Personal",
      project: "Project",
      translate: "Translate selection",
      translating: "Translating",
      translationFailed: "Translation failed",
      viewTranslation: "View translation",
      colors: {
        yellow: "Yellow highlight",
        red: "Red highlight",
        blue: "Blue highlight",
        green: "Green highlight",
        purple: "Purple highlight",
        magenta: "Magenta highlight",
        orange: "Orange highlight",
        gray: "Gray highlight",
      },
    },
    onAsk: fn(),
    onComment: fn(),
    onCopySettled: fn(),
    onHighlight: fn(),
    onOpenTranslation: fn(),
    onTranslate: fn(),
    selection,
  },
  decorators: [
    (Story) => (
      <div
        className="bg-canvas relative mx-auto h-[36rem] w-[28rem] max-w-[100vw] border"
        data-reader-selection-story-boundary
      >
        <span
          aria-hidden="true"
          className="bg-elevated pointer-events-none absolute size-px"
          data-elevated-surface-reference
        />
        <p className="text-secondary absolute top-[34%] left-[24%] text-sm">
          Selected PDF text
        </p>
        <Story />
      </div>
    ),
  ],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ReaderSelectionToolbar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SelectionToolbar: Story = {
  play: async ({ canvasElement }) => {
    await expectOpaqueFloatingSurface(canvasElement, "actions");
  },
};

export const StreamingTranslation: Story = {
  args: {
    translationPreview: {
      status: "streaming",
      text: "检索质量取决于排序",
    },
  },
};

export const CompletedTranslation: Story = {
  args: {
    translationPreview: {
      status: "completed",
      text: "检索质量取决于排序和上下文构建。",
    },
  },
};

export const LongSelectionNearPageTop: Story = {
  args: {
    selection: {
      ...selection,
      anchor: {
        kind: "pdf_text",
        page_number: 4,
        rects: [
          { x: 0.08, y: 0.12, width: 0.84, height: 0.04 },
          { x: 0.08, y: 0.86, width: 0.76, height: 0.04 },
        ],
      },
    },
    translationPreview: {
      status: "completed",
      text: "这是一个跨越多行的长选区，翻译预览必须留在可见的阅读区域内。",
    },
  },
  play: async ({ canvasElement }) => {
    const floating = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-floating]",
    );
    const boundary = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-story-boundary]",
    );
    await expect(floating).not.toBeNull();
    await expect(boundary).not.toBeNull();
    await waitFor(() => {
      const floatingRect = floating!.getBoundingClientRect();
      const boundaryRect = boundary!.getBoundingClientRect();
      expect(floatingRect.top).toBeGreaterThanOrEqual(boundaryRect.top);
      expect(floatingRect.left).toBeGreaterThanOrEqual(boundaryRect.left);
      expect(floatingRect.right).toBeLessThanOrEqual(boundaryRect.right);
      expect(floatingRect.bottom).toBeLessThanOrEqual(boundaryRect.bottom);
    });
  },
};

export const TranslationNearVisibleTop: Story = {
  args: {
    selection: {
      ...selection,
      anchor: {
        kind: "pdf_text",
        page_number: 4,
        rects: [{ x: 0.2, y: 0.03, width: 0.6, height: 0.04 }],
      },
    },
    translationPreview: {
      status: "completed",
      text: "靠近顶部时，翻译预览会自动翻转到选区下方。",
    },
  },
  play: async ({ canvasElement }) => {
    const floating = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-floating]",
    );
    await waitFor(() => {
      expect(floating?.dataset.readerSelectionPlacement).toBe("bottom");
    });
  },
};

export const TranslationNearVisibleTopDark: Story = {
  ...TranslationNearVisibleTop,
  globals: { appearance: "dark" },
};

export const SelectionToolbarSmallMobile: Story = {
  args: TranslationNearVisibleTop.args,
  globals: { viewport: { value: "smallMobile" } },
  play: LongSelectionNearPageTop.play,
};

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
    await expectOpaqueFloatingSurface(canvasElement, "palette");
    const swatches = canvas
      .getByRole("group", {
        name: "Highlight selection",
      })
      .querySelectorAll("button");
    await expect(swatches).toHaveLength(8);
    await expect(
      new Set(
        [...swatches].map((swatch) => getComputedStyle(swatch).backgroundColor),
      ).size,
    ).toBe(8);
  },
};

export const HighlightPaletteDark: Story = {
  globals: { appearance: "dark" },
  play: HighlightPalette.play,
};

export const ProjectAudience: Story = {
  args: { projectContext: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Highlight selection" }),
    );
    const personal = canvas.getByRole("button", { name: "Personal" });
    const project = canvas.getByRole("button", { name: "Project" });
    await expect(personal).toHaveAttribute("aria-pressed", "true");
    await expect(project).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(project);
    await expect(personal).toHaveAttribute("aria-pressed", "false");
    await expect(project).toHaveAttribute("aria-pressed", "true");
  },
};
