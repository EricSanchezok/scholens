import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { authHandlers, actor } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { libraryHandlers } from "./api/handlers";
import { LibraryWorkspace } from "./library-page";

const meta = {
  title: "Features/Library/Papers",
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
      window.history.replaceState({}, "", "/library");
      window.sessionStorage.clear();
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.populated] },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof LibraryWorkspace>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Populated: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", { name: "Library" }),
    ).toBeVisible();
    const titles = await canvas.findAllByText("Attention Is All You Need");
    await expect(
      titles.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(canvas.getByRole("table")).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Previous" }),
    ).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Next" })).toBeEnabled();
  },
};

export const Empty: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.empty] },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText("No papers found"),
    ).toBeVisible();
  },
};

export const Loading: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.loading] },
  },
};

export const Error: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.error] },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText(
        "Papers could not be loaded",
        {},
        { timeout: 3_000 },
      ),
    ).toBeVisible();
  },
};

export const MultiSelect: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const first = await canvas.findByRole("checkbox", {
      name: "Select Attention Is All You Need",
    });
    const second = canvas.getByRole("checkbox", {
      name: /Select Retrieval-Augmented Generation/,
    });
    await userEvent.click(first);
    await userEvent.click(second);
    await expect(canvas.getByText("2 papers selected")).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Remove from library" }),
    ).toBeVisible();
  },
};

export const Processing: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.success, ...libraryHandlers.processing],
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText("Processing paper"),
    ).toBeVisible();
  },
};

export const FailedWithRetry: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...libraryHandlers.failed] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText("Paper processing failed"),
    ).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Retry" })).toBeVisible();
  },
};

export const AddPapers: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Add papers" }),
    );
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Add papers" }),
    ).toBeVisible();
    await expect(body.getByText("PDF files")).toBeVisible();
    await expect(body.getByText("DOI, arXiv, or PDF URL")).toBeVisible();
  },
};

export const Mobile390: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const titles = await canvas.findAllByText("Attention Is All You Need");
    await expect(
      titles.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(canvas.queryByRole("table")).not.toBeInTheDocument();
    await expect(
      canvas.getByRole("button", { name: "Add papers" }),
    ).toBeVisible();
  },
};

export const Mobile430Filters: Story = {
  globals: { viewport: { value: "largeMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Tags" }));
    const body = within(document.body);
    await expect(await body.findByRole("dialog")).toBeVisible();
    await expect(
      body.getByRole("checkbox", { name: "Transformers" }),
    ).toBeVisible();
  },
};

export const Mobile320MultiSelect: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("checkbox", {
        name: "Select Attention Is All You Need",
      }),
    );
    await expect(canvas.getByText("1 paper selected")).toBeVisible();
  },
};

export const Mobile390AddPapers: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      await within(canvasElement).findByRole("button", { name: "Add papers" }),
    );
    await expect(
      await within(document.body).findByRole("heading", { name: "Add papers" }),
    ).toBeVisible();
  },
};

export const Mobile390Processing: Story = {
  ...Processing,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Mobile390FailedWithRetry: Story = {
  ...FailedWithRetry,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Mobile390Empty: Story = {
  ...Empty,
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Mobile430Loading: Story = {
  ...Loading,
  globals: { viewport: { value: "largeMobile", isRotated: false } },
};

export const Mobile320Error: Story = {
  ...Error,
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};
