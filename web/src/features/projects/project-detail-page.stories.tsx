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

export const OverviewCollapsed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = await canvas.findByRole("heading", { name: "Truthward" });
    await expect(heading).toBeVisible();
    const workbenchHeader = heading.closest("header");
    await expect(workbenchHeader).not.toBeNull();
    const tabs = canvas.getByRole("tablist");
    if (workbenchHeader) {
      await expect(
        Math.round(
          tabs.getBoundingClientRect().top -
            workbenchHeader.getBoundingClientRect().bottom,
        ),
      ).toBe(16);
    }
    await expect(
      canvas.queryByRole("region", { name: "Project chat" }),
    ).not.toBeInTheDocument();
    await expect(canvas.getByText("Recent papers")).toBeVisible();
    await expect(
      canvas.getByRole("heading", { name: "Collaboration" }),
    ).toBeVisible();
    await expect(canvas.getByText("2 members")).toBeVisible();
    await expect(await canvas.findByText("Eric Sanchez")).toBeVisible();
    await expect(await canvas.findByText("Mina Park")).toBeVisible();
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
    await expect(canvas.getByRole("button", { name: "Manage" })).toBeVisible();
  },
};

export const ChatExpanded: Story = {
  parameters: {
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/projects/${projectId}?panel=chat&conversation=40000000-0000-4000-8000-000000000001`,
        pathname: `/projects/${projectId}`,
        query: {
          conversation: "40000000-0000-4000-8000-000000000001",
          panel: "chat",
        },
      },
    },
  },
  loaders: [
    async () => {
      resetRefreshForTests();
      window.history.replaceState(
        {},
        "",
        `/projects/${projectId}?panel=chat&conversation=40000000-0000-4000-8000-000000000001`,
      );
      return {};
    },
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("region", { name: "Project chat" }),
    ).toBeVisible();
    await userEvent.click(
      await canvas.findByRole("button", {
        name: "Compare retrieval baselines",
      }),
    );
    const body = within(document.body);
    const history = await body.findByRole("dialog", {
      name: "Conversation history",
    });
    await expect(within(history).getByText("Pinned")).toBeVisible();
    await expect(within(history).getByText("Recent")).toBeVisible();
    await expect(
      within(history).getByRole("button", { name: "Unpin conversation" }),
    ).toBeVisible();
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
    await expect(
      canvas.queryByRole("button", { name: "Add papers" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", { name: "Manage project" }),
    );
    await userEvent.click(
      within(document.body).getByRole("menuitem", { name: "Add papers" }),
    );
    await expect(
      await within(document.body).findByRole("heading", {
        name: "Add papers from Library",
      }),
    ).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(
      canvas.getAllByRole("button", { name: "Open paper actions" })[0]!,
    );
    await userEvent.click(
      within(document.body).getByRole("menuitem", {
        name: "Remove from project",
      }),
    );
    const impactDialog = await within(document.body).findByRole("alertdialog");
    await expect(
      within(impactDialog).getByText(/2 project annotation threads/),
    ).toBeVisible();
    await userEvent.click(
      within(impactDialog).getByRole("button", {
        name: "Remove paper and annotations",
      }),
    );
  },
};

export const PaperSearchResults: Story = {
  parameters: {
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/projects/${projectId}?view=papers&paper_q=code%20world`,
        pathname: `/projects/${projectId}`,
        query: { paper_q: "code world", view: "papers" },
      },
    },
  },
  loaders: [
    async () => {
      window.history.replaceState(
        {},
        "",
        `/projects/${projectId}?view=papers&paper_q=code%20world`,
      );
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
      canvas.getByRole("searchbox", { name: "Search project papers" }),
    ).toHaveValue("code world");
  },
};

export const PaperRemovalImpact: Story = {
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
    await userEvent.click(
      (
        await canvas.findAllByRole("button", {
          name: "Open paper actions",
        })
      )[0]!,
    );
    await userEvent.click(
      within(document.body).getByRole("menuitem", {
        name: "Remove from project",
      }),
    );
    const impactDialog = await within(document.body).findByRole("alertdialog");
    await expect(
      within(impactDialog).getByText(/2 project annotation threads/),
    ).toBeVisible();
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
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("region", { name: "Project chat" }),
    ).toBeVisible();
    await expect(
      body.getByRole("button", { name: "Close project chat" }),
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

export const Mobile430: Story = {
  globals: { viewport: { value: "mobile" } },
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

export const LongTitle: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...projectHandlers.longTitle] },
  },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};

export const ChineseDark: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
};

export const WithoutPaperManagement: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...projectHandlers.noPaperManagement],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Manage project" }),
    );
    await expect(
      within(document.body).queryByRole("menuitem", { name: "Add papers" }),
    ).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
  },
};
