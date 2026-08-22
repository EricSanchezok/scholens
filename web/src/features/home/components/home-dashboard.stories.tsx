import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { homePapers, homeProjects } from "../api/fixtures";
import { HomeDashboard } from "./home-dashboard";

const longEnglishPaperTitle =
  "Holos: A Web-Scale LLM-Based Multi-Agent System for Open-Ended Scientific Collaboration";
const longCjkPaperTitle =
  "面向开放式科研协作与长期知识积累的超大规模多智能体系统研究";
const longTitlePapers = homePapers.map((paper, index) => ({
  ...paper,
  document: {
    ...paper.document,
    title:
      index === 0
        ? longEnglishPaperTitle
        : index === 1
          ? longCjkPaperTitle
          : paper.document.title,
  },
}));

const meta = {
  title: "Features/Home/Dashboard",
  component: HomeDashboard,
  args: {
    papers: homePapers,
    projects: homeProjects,
    context: { kind: "library" },
    reasoningLevel: "standard",
    onContextChange: fn(),
    onReasoningLevelChange: fn(),
    onSubmit: fn(async () => undefined),
    onRetryPapers: fn(),
    onRetryProjects: fn(),
  },
  decorators: [
    (Story) => (
      <div className="h-screen">
        <Story />
      </div>
    ),
  ],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof HomeDashboard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const recentCards = Array.from(
      canvasElement.querySelectorAll<HTMLElement>("[data-home-recent-card]"),
    );
    await expect(recentCards.length).toBeGreaterThan(0);
    for (const card of recentCards) {
      await expect(card.dataset.slot).toBe("frame");
      await expect(
        card.querySelector('[data-slot="frame-panel"]'),
      ).not.toBeInTheDocument();
      const nestedClosedBorders = Array.from(card.querySelectorAll("*")).filter(
        (element) => {
          const style = getComputedStyle(element);
          return [
            style.borderTopWidth,
            style.borderRightWidth,
            style.borderBottomWidth,
            style.borderLeftWidth,
          ].every((width) => Number(width.replace("px", "")) > 0);
        },
      );
      await expect(nestedClosedBorders).toHaveLength(0);
    }
  },
};

export const PapersOnly: Story = {
  args: { projects: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Recent papers")).toBeVisible();
    await expect(canvas.queryByText("Recent projects")).not.toBeInTheDocument();
  },
};

export const ProjectsOnly: Story = {
  args: { papers: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Recent projects")).toBeVisible();
    await expect(canvas.queryByText("Recent papers")).not.toBeInTheDocument();
  },
};

export const Empty: Story = {
  args: { papers: [], projects: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/Ask across a paper/)).toBeVisible();
    await expect(canvas.queryByText("Recent papers")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Recent projects")).not.toBeInTheDocument();
  },
};

export const MobileRecents: Story = {
  args: { showComposer: false },
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const hero = canvasElement.querySelector<HTMLElement>("[data-home-hero]");
    const launcher = canvasElement.querySelector<HTMLElement>(
      "[data-mobile-recent-launcher]",
    );
    await expect(canvas.getByText("继续最近研究")).toBeVisible();
    await expect(canvas.getByText("基于你的研究资料提问。")).not.toBeVisible();
    await expect(canvas.getByText("最近论文")).not.toBeVisible();
    await expect(hero).not.toBeNull();
    await expect(launcher).not.toBeNull();
    await expect(["left", "start"]).toContain(
      getComputedStyle(hero!).textAlign,
    );
    const heroBounds = hero!.getBoundingClientRect();
    const launcherBounds = launcher!.getBoundingClientRect();
    await expect(launcherBounds.top - heroBounds.bottom).toBeGreaterThanOrEqual(
      48,
    );
    await expect(launcherBounds.top - heroBounds.bottom).toBeLessThanOrEqual(
      64,
    );
    await expect(
      Math.abs(launcherBounds.left - heroBounds.left),
    ).toBeLessThanOrEqual(4);
    await userEvent.click(
      canvas.getByRole("button", {
        name: /将论文《Attention Is All You Need》设为研究范围/,
      }),
    );
    await expect(args.onContextChange).toHaveBeenCalledWith({
      kind: "selection",
      project_ids: [],
      document_ids: [homePapers[0]!.document.document_id],
    });
  },
};

export const MobileRecentsLongTitles: Story = {
  args: { papers: longTitlePapers, projects: [], showComposer: false },
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const launcher = await canvas.findByRole("button", {
      name: new RegExp(longEnglishPaperTitle),
    });
    const title = within(launcher).getByText(longEnglishPaperTitle);
    await expect(getComputedStyle(title).webkitLineClamp).toBe("2");
    await expect(launcher.scrollWidth).toBeLessThanOrEqual(
      launcher.clientWidth,
    );
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};

export const MobileRecentsLoading: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  args: {
    papers: [],
    projects: [],
    papersLoading: true,
    projectsLoading: true,
    showComposer: false,
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("status", {
        name: "Loading recent research",
      }),
    ).toBeVisible();
  },
};

export const MobileRecentsError: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  args: {
    papers: [],
    projects: [],
    papersError: true,
    projectsError: true,
    showComposer: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const visibleError = canvas
      .getAllByText("Could not load recent research")
      .find((element) => element.getClientRects().length > 0);
    await expect(visibleError).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Try again" }),
    ).toBeVisible();
  },
};
