import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import {
  expect,
  fireEvent,
  fn,
  userEvent,
  waitFor,
  within,
} from "storybook/test";

import { ResearchComposer } from "@/features/conversation";
import { homePapers, homeProjects } from "../api/fixtures";

const meta = {
  title: "Features/Home/Research Composer",
  component: ResearchComposer,
  args: {
    context: { kind: "library" },
    surface: "workspace",
    papers: homePapers,
    projects: homeProjects,
    reasoningLevel: "standard",
    onContextChange: fn(),
    onReasoningLevelChange: fn(),
    onSubmit: fn(async () => undefined),
    onStop: fn(),
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-screen items-end p-2">
        <Story />
      </div>
    ),
  ],
  globals: { locale: "zh-CN", viewport: { value: "mobile", isRotated: false } },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ResearchComposer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const LibraryScope: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", {
        name: "研究范围：资料库",
      }),
    ).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "思考强度：标准" }),
    ).toBeNull();
  },
};

export const MultiplePapersScope: Story = {
  args: {
    context: {
      kind: "selection",
      project_ids: [],
      document_ids: homePapers
        .slice(0, 2)
        .map((paper) => paper.document.document_id),
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const contextButton = canvas.getByRole("button", {
      name: "研究范围：2 篇",
    });
    await expect(
      within(contextButton).getByText("2", { selector: "span" }),
    ).toBeVisible();
  },
};

export const DesktopSelectedContext: Story = {
  args: {
    context: {
      kind: "selection",
      project_ids: [],
      document_ids: [homePapers[0]!.document.document_id],
    },
  },
  globals: {
    locale: "zh-CN",
    viewport: { value: "desktop", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const composer = canvas.getByRole("textbox", { name: "问任何问题" });
    const form = composer.closest("form");
    await expect(form).not.toBeNull();
    if (!form) return;
    await expect(form).toHaveAttribute("data-has-context", "true");
    await expect(form).toHaveAttribute("data-expanded", "false");
    const contextButton = canvas.getByRole("button", {
      name: /研究范围：/,
    });
    await expect(
      within(contextButton).getByText("1", { selector: "span" }),
    ).toBeVisible();
    await expect(canvas.queryByText("1 个来源")).toBeNull();
    await expect(form.getBoundingClientRect().height).toBeLessThan(80);
    await expect(
      Number.parseFloat(getComputedStyle(form).borderRadius),
    ).toBeGreaterThanOrEqual(999);
  },
};

export const ManySelectedSources: Story = {
  args: {
    context: {
      kind: "selection",
      project_ids: [],
      document_ids: Array.from(
        { length: 12 },
        (_, index) => `document-${index + 1}`,
      ),
    },
  },
  globals: {
    locale: "zh-CN",
    viewport: { value: "desktop", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    const contextButton = within(canvasElement).getByRole("button", {
      name: "研究范围：12 篇",
    });
    await expect(within(contextButton).getByText("9+")).toBeVisible();
  },
};

export const LongProjectScope: Story = {
  args: {
    projects: [
      {
        ...homeProjects[0]!,
        title: "面向长上下文推理的多阶段研究项目",
      },
    ],
    context: {
      kind: "selection",
      project_ids: [homeProjects[0]!.id],
      document_ids: [],
    },
  },
  globals: {
    locale: "zh-CN",
    viewport: { value: "smallMobile", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", {
        name: "研究范围：面向长上下文推理的多阶段研究项目",
      }),
    ).toBeVisible();
  },
};

export const MultilineInput: Story = {
  play: async ({ canvasElement }) => {
    const composer = within(canvasElement).getByRole("textbox", {
      name: "问任何问题",
    });
    const form = composer.closest("form");
    await expect(form).not.toBeNull();
    if (!form) return;
    const restingBounds = form.getBoundingClientRect();
    await userEvent.type(
      composer,
      "比较论文方法{Shift>}{Enter}{/Shift}说明推理成本{Shift>}{Enter}{/Shift}列出关键差异",
    );
    await expect(composer).toHaveValue(
      "比较论文方法\n说明推理成本\n列出关键差异",
    );
    await expect(form).toHaveAttribute("data-expanded", "true");
    await waitFor(() =>
      expect(
        Number.parseFloat(getComputedStyle(form).borderRadius),
      ).toBeCloseTo(24, 0),
    );
    const expandedBounds = form.getBoundingClientRect();
    await expect(Math.round(expandedBounds.bottom)).toBe(
      Math.round(restingBounds.bottom),
    );
    await expect(expandedBounds.top).toBeLessThan(restingBounds.top);
  },
};

export const DesktopLongInputKeepsControlsTrailing: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "desktop", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const composer = canvas.getByRole("textbox", { name: "问任何问题" });
    const form = composer.closest("form");
    await expect(form).not.toBeNull();
    if (!form) return;

    await fireEvent.change(composer, {
      target: { value: "这是一段足够长的桌面端测试内容 ".repeat(80) },
    });
    await waitFor(() => expect(form).toHaveAttribute("data-expanded", "true"));

    const reasoning = canvas.getByRole("button", {
      name: "思考强度：标准",
    });
    const submit = canvas.getByRole("button", { name: "询问 Scholens" });
    await expect(
      Math.round(
        submit.getBoundingClientRect().left -
          reasoning.getBoundingClientRect().right,
      ),
    ).toBeLessThanOrEqual(8);
    await expect(
      Math.round(
        form.getBoundingClientRect().right -
          submit.getBoundingClientRect().right,
      ),
    ).toBeLessThanOrEqual(16);
  },
};

export const ImeCandidateConfirmation: Story = {
  args: { onSubmit: fn(async () => undefined) },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const composer = canvas.getByRole("textbox", { name: "问任何问题" });
    await fireEvent.compositionStart(composer);
    await fireEvent.change(composer, { target: { value: "你好" } });
    await waitFor(() =>
      expect(
        canvas.getByRole("button", { name: "询问 Scholens" }),
      ).toBeEnabled(),
    );

    await fireEvent.keyDown(composer, {
      code: "Enter",
      isComposing: true,
      key: "Enter",
      keyCode: 229,
    });
    await expect(args.onSubmit).not.toHaveBeenCalled();
    await expect(composer).toHaveValue("你好");

    await fireEvent.compositionEnd(composer, { data: "你好" });
    await fireEvent.keyDown(composer, { code: "Enter", key: "Enter" });
    await waitFor(() => expect(args.onSubmit).toHaveBeenCalledWith("你好"));
  },
};

export const DesktopReasoningMenuOpen: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "desktop", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "思考强度：标准" });
    const chevron = trigger.querySelector<HTMLElement>(
      '[data-slot="reasoning-menu-chevron"]',
    );
    const restingBackground = getComputedStyle(trigger).backgroundColor;
    await expect(chevron).not.toBeNull();
    await userEvent.click(trigger);
    const page = within(canvasElement.ownerDocument.body);
    await expect(page.getByText("快速、均衡的推理")).toBeVisible();
    await expect(page.getByText("更充分地分析复杂问题")).toBeVisible();
    await expect(trigger).toHaveAttribute("data-state", "open");
    await expect(getComputedStyle(chevron!).transitionProperty).toContain(
      "rotate",
    );
    await waitFor(() =>
      expect(getComputedStyle(trigger).backgroundColor).not.toBe(
        restingBackground,
      ),
    );
    await waitFor(() =>
      expect(getComputedStyle(chevron!).rotate).toBe("180deg"),
    );
    const standard = page.getByRole("menuitemradio", { name: /标准/ });
    const deep = page.getByRole("menuitemradio", { name: /深入/ });
    await expect(standard).toHaveAttribute("aria-checked", "true");
    await expect(deep).toHaveAttribute("aria-checked", "false");
    await expect(
      standard.querySelector('[data-slot="dropdown-menu-radio-indicator"] svg'),
    ).not.toBeNull();
    await expect(
      deep.querySelector('[data-slot="dropdown-menu-radio-indicator"] svg'),
    ).toBeNull();
    await userEvent.keyboard("{Escape}");
    await expect(trigger).toHaveFocus();
    await expect(trigger).toHaveAttribute("data-state", "closed");
  },
};

export const StreamingStop: Story = {
  args: { busy: true, stopAvailable: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "停止生成" }),
    ).toBeVisible();
  },
};

export const DarkEnglishLarge: Story = {
  globals: {
    appearance: "dark",
    locale: "en",
    viewport: { value: "largeMobile", isRotated: false },
  },
};
