import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { actor, authHandlers } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { projectFixtures } from "./api/fixtures";
import { projectHandlers } from "./api/handlers";
import { ProjectDetailWorkspace } from "./project-detail-page";

const projectId = projectFixtures[0]!.id;
const meta = {
  title: "Features/Projects/Detail",
  component: ProjectDetailWorkspace,
  args: { actor, projectId },
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
      window.history.replaceState({}, "", `/projects/${projectId}`);
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: [...authHandlers.success, ...projectHandlers.populated] },
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/projects/${projectId}`,
        pathname: `/projects/${projectId}`,
        query: {},
      },
    },
  },
} satisfies Meta<typeof ProjectDetailWorkspace>;

export default meta;
type Story = StoryObj<typeof meta>;

export const OverviewWithChat: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", { name: "Truthward" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("region", { name: "Project chat" }),
    ).toBeVisible();
    await expect(canvas.getByText("Recent papers")).toBeVisible();
  },
};

export const Papers: Story = {
  parameters: {
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/projects/${projectId}?view=papers`,
        pathname: `/projects/${projectId}`,
        query: { view: "papers" },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const paperTitles = await canvas.findAllByText("Attention Is All You Need");
    await expect(
      paperTitles.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await userEvent.click(canvas.getByRole("button", { name: "Add papers" }));
    await expect(
      await within(document.body).findByRole("heading", {
        name: "Add papers from Library",
      }),
    ).toBeVisible();
    await userEvent.keyboard("{Escape}");
  },
};

export const Outputs: Story = {
  parameters: {
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/projects/${projectId}?view=outputs`,
        pathname: `/projects/${projectId}`,
        query: { view: "outputs" },
      },
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText("Citation"),
    ).toBeVisible();
  },
};

export const PapersEmpty: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...projectHandlers.papersEmpty],
    },
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/projects/${projectId}?view=papers`,
        pathname: `/projects/${projectId}`,
        query: { view: "papers" },
      },
    },
  },
};

export const OutputsEmpty: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...projectHandlers.outputsEmpty],
    },
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/projects/${projectId}?view=outputs`,
        pathname: `/projects/${projectId}`,
        query: { view: "outputs" },
      },
    },
  },
};

export const MobileChat: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  parameters: {
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/projects/${projectId}?panel=chat`,
        pathname: `/projects/${projectId}`,
        query: { panel: "chat" },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("region", { name: "Project chat" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Return to project" }),
    ).toBeVisible();
  },
};

export const Tablet768: Story = {
  globals: { viewport: { value: "tablet", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("button", { name: "Chat" }),
    ).toBeVisible();
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};
