import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import {
  expectLayeredKeyboardFocus,
  focusWithKeyboard,
  readFocusVisual,
} from "@/components/ui/focus-contract.story-test";
import { cn } from "@/lib/utilities/cn";
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
    (Story, context) => (
      <div
        className={cn(
          "bg-canvas relative mx-auto max-w-[100vw] border",
          context.parameters.readerSelectionBoundary === "wide"
            ? "h-[50rem] w-[min(100vw,160rem)]"
            : "h-[36rem] w-[28rem]",
        )}
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
  play: async ({ canvasElement }) => {
    const text = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-translation-text]",
    );
    await expect(text).not.toBeNull();
    await expect(getComputedStyle(text!).overflowY).toBe("auto");
    await expect(text!).toHaveAttribute("tabindex", "0");
  },
};

export const EdgeBlockedTranslation: Story = {
  args: {
    translationPreview: {
      status: "error",
      text: "",
      errorCode: "edge_blocked",
    },
  },
  play: async ({ canvasElement }) => {
    const preview = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-translation-preview]",
    );
    const header = preview?.querySelector<HTMLElement>(
      "[data-reader-selection-translation-status]",
    );
    const body = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-translation-text]",
    );
    await expect(preview).not.toBeNull();
    await expect(header).not.toBeNull();
    await expect(body).not.toBeNull();
    await expect(body!.textContent).not.toBe(header!.textContent);
    await expect(body!.textContent).toContain("network edge");
  },
};

export const LongCompletedTranslationTeaser: Story = {
  args: {
    translationPreview: {
      status: "completed",
      text: "检索质量取决于排序和上下文构建。完整的翻译结果只保证出现在右侧翻译面板中，桌面预览是一个可滚动摘要。检索质量取决于排序和上下文构建。".repeat(
        6,
      ),
    },
  },
  play: async ({ canvasElement }) => {
    const text = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-translation-text]",
    );
    const boundary = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-story-boundary]",
    );
    await expect(text).not.toBeNull();
    await expect(boundary).not.toBeNull();
    await waitFor(() => {
      const textRect = text!.getBoundingClientRect();
      expect(textRect.height).toBeGreaterThan(96);
      expect(getComputedStyle(text!).overflowY).toBe("auto");
      expect(text!.scrollHeight).toBeGreaterThan(text!.clientHeight);
    });
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

export const SelectionNearHorizontalEdges: Story = {
  args: {
    selection: {
      ...selection,
      anchor: {
        kind: "pdf_text",
        page_number: 4,
        rects: [{ x: 0.01, y: 0.42, width: 0.2, height: 0.04 }],
      },
    },
    translationPreview: {
      status: "completed",
      text: "长单词和 URL https://example.com/research/reader-selection-translation-stability 应该安全换行。",
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
      expect(floatingRect.left).toBeGreaterThanOrEqual(boundaryRect.left);
      expect(floatingRect.right).toBeLessThanOrEqual(boundaryRect.right);
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

export const TranslationNearVisibleBottom: Story = {
  args: {
    selection: {
      ...selection,
      anchor: {
        kind: "pdf_text",
        page_number: 4,
        rects: [{ x: 0.2, y: 0.86, width: 0.6, height: 0.04 }],
      },
    },
    translationPreview: {
      status: "streaming",
      text: "这是一个持续增长的流式翻译预览，用于验证方向锁定。",
    },
  },
  play: async ({ canvasElement }) => {
    const floating = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-floating]",
    );
    await waitFor(() => {
      expect(floating?.dataset.readerSelectionPlacement).toBe("top");
    });
  },
};

export const LongStreamingTranslation: Story = {
  args: {
    translationPreview: {
      status: "streaming",
      text: "这是一段持续增长的翻译内容。".repeat(32),
    },
  },
  play: async ({ canvasElement }) => {
    const text = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-translation-text]",
    );
    const floating = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-floating]",
    );
    await expect(text).not.toBeNull();
    await expect(floating).not.toBeNull();
    await waitFor(() => {
      expect(getComputedStyle(text!).overflowY).toBe("auto");
      expect(text!.scrollHeight).toBeGreaterThan(text!.clientHeight);
      expect(floating!.dataset.readerSelectionPlacement).toBe("bottom");
    });
  },
};

export const LongStreamingTranslationReducedMotion: Story = {
  ...LongStreamingTranslation,
  globals: { motion: "reduced" },
};

export const WideDesktopPreview: Story = {
  ...LongCompletedTranslationTeaser,
  parameters: { readerSelectionBoundary: "wide" },
};

export const KeyboardScrollablePreview: Story = {
  args: LongStreamingTranslation.args,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const previewText = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-translation-text]",
    );
    await expect(previewText).not.toBeNull();
    await expect(
      canvas.getByRole("button", { name: "View translation" }),
    ).toBeVisible();
    previewText!.focus();
    await expect(previewText!).toHaveFocus();
    await userEvent.keyboard("{PageDown}");
  },
};

export const TranslationNearVisibleTopDark: Story = {
  ...TranslationNearVisibleTop,
  globals: { appearance: "dark" },
};

export const SelectionToolbarSmallMobile: Story = {
  args: TranslationNearVisibleTop.args,
  globals: { viewport: { value: "smallMobile" } },
  play: async (context) => {
    await LongSelectionNearPageTop.play?.(context);
    await expect(
      context.canvasElement.querySelector(
        "[data-reader-selection-translation-preview]",
      ),
    ).toBeNull();
  },
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
      .querySelectorAll<HTMLButtonElement>("button");
    await expect(swatches).toHaveLength(8);
    const colorDiscs = [...swatches].map((swatch) =>
      swatch.querySelector<HTMLElement>(":scope > span"),
    );
    await expect(colorDiscs.every(Boolean)).toBe(true);
    await expect(
      new Set(colorDiscs.map((disc) => getComputedStyle(disc!).backgroundColor))
        .size,
    ).toBe(8);

    const yellow = swatches[0]!;
    const yellowDisc = colorDiscs[0]!;
    const restingButton = readFocusVisual(yellow);
    const restingDisc = readFocusVisual(yellowDisc);
    await focusWithKeyboard(yellow);
    await expectLayeredKeyboardFocus({
      element: yellow,
      resting: restingButton,
    });
    await expect(readFocusVisual(yellowDisc).backgroundColor).toBe(
      restingDisc.backgroundColor,
    );
    await expect(readFocusVisual(yellowDisc).boxShadow).toBe(
      restingDisc.boxShadow,
    );
  },
};

export const HighlightPaletteDark: Story = {
  globals: { appearance: "dark" },
  play: HighlightPalette.play,
};

export const HighlightPaletteSmallMobile: Story = {
  globals: { viewport: { value: "smallMobile" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Highlight selection" }),
    );
    const palette = canvasElement.querySelector<HTMLElement>(
      "[data-reader-highlight-palette]",
    );
    const boundary = canvasElement.querySelector<HTMLElement>(
      "[data-reader-selection-story-boundary]",
    );
    await expect(palette).not.toBeNull();
    await expect(boundary).not.toBeNull();
    await waitFor(() => {
      const boundaryRect = boundary!.getBoundingClientRect();
      const paletteRect = palette!.getBoundingClientRect();
      expect(paletteRect.left).toBeGreaterThanOrEqual(boundaryRect.left);
      expect(paletteRect.right).toBeLessThanOrEqual(boundaryRect.right);
      expect(palette!.querySelectorAll("button")).toHaveLength(8);
      for (const swatch of palette!.querySelectorAll("button")) {
        const rect = swatch.getBoundingClientRect();
        expect(rect.left).toBeGreaterThanOrEqual(boundaryRect.left);
        expect(rect.right).toBeLessThanOrEqual(boundaryRect.right);
      }
    });
  },
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
