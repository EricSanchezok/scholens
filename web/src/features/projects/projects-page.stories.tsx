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

export const Populated: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", { name: "Projects" }),
    ).toBeVisible();
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
    await expect(
      await within(canvasElement).findByText(
        "Start your first research project",
      ),
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
    await expect(
      await canvas.findByRole("link", { name: "Truthward" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "New project" }),
    ).toBeVisible();
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};

export const LargeMobile430: Story = {
  globals: { viewport: { value: "largeMobile", isRotated: false } },
};

export const SmallMobile320: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
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
