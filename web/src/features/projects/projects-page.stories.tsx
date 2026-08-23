import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { actor, authHandlers } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { projectHandlers } from "./api/handlers";
import { ProjectsWorkspace } from "./projects-page";

const meta = {
  title: "Features/Projects/List",
  component: ProjectsWorkspace,
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
      window.history.replaceState({}, "", "/projects");
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: [...authHandlers.success, ...projectHandlers.populated] },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof ProjectsWorkspace>;

export default meta;
type Story = StoryObj<typeof meta>;

async function expectProjectRowsContained(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  await expect(
    await canvas.findByRole("link", { name: "Truthward" }),
  ).toBeVisible();
  const canvasRect = canvasElement.getBoundingClientRect();
  const rows =
    canvasElement.querySelectorAll<HTMLElement>("[data-project-row]");
  await expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    const rect = row.getBoundingClientRect();
    await expect(rect.left).toBeGreaterThanOrEqual(Math.floor(canvasRect.left));
    await expect(rect.right).toBeLessThanOrEqual(Math.ceil(canvasRect.right));
  }
}

export const Populated: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = await canvas.findByRole("heading", { name: "Projects" });
    await expect(heading).toBeVisible();
    await expect(heading).toHaveClass("text-2xl");
    const workbenchHeader = heading.closest("header");
    await expect(workbenchHeader).not.toBeNull();
    const search = await canvas.findByRole("searchbox", {
      name: "Search projects",
    });
    const utilityToolbar = search.closest<HTMLElement>(
      "[data-collection-toolbar]",
    );
    await expect(utilityToolbar).not.toBeNull();
    if (workbenchHeader) {
      await expect(
        Math.round(
          utilityToolbar!.getBoundingClientRect().top -
            workbenchHeader.getBoundingClientRect().bottom,
        ),
      ).toBe(16);
    }
    const createButton = canvas.getByRole("button", { name: "New project" });
    await expect(createButton.querySelector("svg")).toHaveClass(
      "text-ui-icon-inverse",
    );
    await expect(
      await canvas.findByRole("link", { name: "Truthward" }),
    ).toBeVisible();
    await expect(await canvas.findByText("18")).toBeVisible();
  },
};

export const Empty: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...projectHandlers.empty] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText("Start your first research project"),
    ).toBeVisible();
    await expect(
      canvas.getAllByRole("button", { name: "New project" }),
    ).toHaveLength(1);
  },
};

export const FilteredEmpty: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...projectHandlers.empty] },
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: "/projects?q=missing",
        pathname: "/projects",
        query: { q: "missing" },
      },
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText("No matching projects"),
    ).toBeVisible();
  },
};

export const Loading: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...projectHandlers.loading] },
  },
};

export const Error: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...projectHandlers.error] },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText(
        "Projects could not be loaded",
        {},
        { timeout: 3_000 },
      ),
    ).toBeVisible();
  },
};

export const CreateProject: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "New project" }),
    );
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Create a project" }),
    ).toBeVisible();
    await expect(body.getByLabelText("Project name")).toHaveFocus();
    await userEvent.keyboard("{Escape}");
  },
};

export const Mobile390: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expectProjectRowsContained(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "New project" }),
    ).toBeVisible();
    const search = canvas.getByRole("searchbox", { name: "Search projects" });
    const sort = canvas.getByRole("combobox", { name: "Sort projects" });
    await expect(
      Math.abs(
        search.getBoundingClientRect().top - sort.getBoundingClientRect().top,
      ),
    ).toBeLessThanOrEqual(1);
    await expect(search.closest('[data-slot="frame"]')).toBeNull();
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};

export const LargeMobile430: Story = {
  globals: { viewport: { value: "largeMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    await expectProjectRowsContained(canvasElement);
  },
};

export const SmallMobile320: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    await expectProjectRowsContained(canvasElement);
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};

export const DarkChinese: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", { name: "项目" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "新建项目" }),
    ).toBeVisible();
  },
};
