import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { authHandlers, actor } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { libraryHandlers } from "./api/handlers";
import { LibraryWorkspace } from "./library-page";

const meta = {
  title: "Features/Library/Outputs",
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
      window.history.replaceState({}, "", "/library?tab=outputs");
      window.sessionStorage.clear();
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.populated] },
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: "/library?tab=outputs",
        pathname: "/library",
        query: { tab: "outputs" },
      },
    },
  },
} satisfies Meta<typeof LibraryWorkspace>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Populated: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table");
    await expect(table).toBeVisible();
    const tableView = within(table);
    await expect(tableView.getByText("Architecture notes")).toBeVisible();
    await expect(tableView.getByText("Annotations")).toBeVisible();
    await expect(tableView.getByText("Citations")).toBeVisible();
    await expect(tableView.getByText("Audio overviews")).toBeVisible();
    await expect(tableView.getByText("Data tables")).toBeVisible();
    await expect(
      canvas.getAllByRole("button", { name: "Not available yet" })[0],
    ).toBeDisabled();
  },
};

export const Empty: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...libraryHandlers.outputsEmpty],
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText("No outputs found"),
    ).toBeVisible();
  },
};

export const Loading: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...libraryHandlers.outputsLoading],
    },
  },
};

export const Error: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...libraryHandlers.outputsError],
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText(
        "Outputs could not be loaded",
        {},
        { timeout: 3_000 },
      ),
    ).toBeVisible();
  },
};

export const Filtered: Story = {
  parameters: {
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: "/library?tab=outputs&kind=citation",
        pathname: "/library",
        query: { kind: "citation", tab: "outputs" },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("button", { name: /Types/ }),
    ).toHaveTextContent("1");
  },
};

export const DarkChinese: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table");
    await expect(within(table).getByText("标注")).toBeVisible();
    await expect(
      within(table).getAllByRole("button", { name: "尚未开放" })[0],
    ).toBeDisabled();
  },
};

export const Mobile390: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const titles = await canvas.findAllByText("Architecture notes");
    await expect(
      titles.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(canvas.queryByRole("table")).not.toBeInTheDocument();
  },
};

export const Mobile430Filters: Story = {
  globals: { viewport: { value: "largeMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Types" }));
    const body = within(document.body);
    await expect(await body.findByRole("dialog")).toBeVisible();
    await expect(
      body.getByRole("checkbox", { name: "Annotations" }),
    ).toBeVisible();
  },
};

export const Mobile320Empty: Story = {
  ...Empty,
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};

export const Mobile390Loading: Story = {
  ...Loading,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Mobile430Error: Story = {
  ...Error,
  globals: { viewport: { value: "largeMobile", isRotated: false } },
};
