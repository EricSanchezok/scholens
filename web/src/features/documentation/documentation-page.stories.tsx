import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { DocumentationPage } from "./documentation-page";

const meta = {
  title: "Features/Documentation/MCP Guide",
  component: DocumentationPage,
  args: { selectedClient: "codex" },
  argTypes: {
    selectedClient: {
      control: "select",
      options: ["codex", "claude-desktop", "cursor", "generic"],
    },
  },
  parameters: {
    layout: "fullscreen",
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof DocumentationPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const writeText = fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    await expect(
      canvas.getByRole("heading", {
        level: 1,
        name: "Connect your research agent to Scholens",
      }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("link", { name: /Create access key/ }),
    ).toHaveAttribute("href", "/?settings=access-keys");
    await expect(
      canvas.getAllByText("http://127.0.0.1:7301/mcp")[0],
    ).toBeVisible();
    await expect(
      canvas.getByText(/Development preview: the connector uses mutable/),
    ).toBeVisible();
    const copy = canvas.getAllByRole("button", { name: "Copy code" })[0]!;
    await userEvent.click(copy);
    await expect(
      canvas.getAllByRole("button", { name: "Code copied" })[0],
    ).toBeVisible();
    await expect(writeText).toHaveBeenCalledTimes(1);
  },
};

export const Cursor: Story = {
  args: { selectedClient: "cursor" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(/Bearer \$\{env:SCHOLENS_ACCESS_KEY\}/),
    ).toBeVisible();
    await expect(canvas.getByRole("link", { name: "Cursor" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  },
};

export const ChineseDark: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", {
        level: 1,
        name: "将你的研究智能体连接到 Scholens",
      }),
    ).toBeVisible();
    await expect(canvas.getByText("明确的产品边界")).toBeVisible();
  },
};

export const Mobile: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const LargeMobile: Story = {
  args: { selectedClient: "claude-desktop" },
  globals: { viewport: { value: "largeMobile", isRotated: false } },
};

export const SmallMobile: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const compactToc =
      canvasElement.querySelector<HTMLSummaryElement>("details > summary");
    await expect(compactToc).not.toBeNull();
    if (!compactToc) throw new Error("Compact documentation TOC is missing");
    await expect(compactToc).toHaveTextContent("On this page");
    await expect(compactToc).toBeVisible();
    await userEvent.click(compactToc);

    const compactTocDetails = compactToc.closest("details");
    await expect(compactTocDetails).not.toBeNull();
    const touchTargets = [
      ...within(
        canvas.getByRole("group", { name: "Documentation language" }),
      ).getAllByRole("button"),
      canvasElement.querySelector('header a[href="/"]'),
      compactToc,
      ...within(compactTocDetails as HTMLElement).getAllByRole("link"),
      canvas.getByRole("link", {
        name: "Open the client's official MCP documentation",
      }),
      ...canvasElement.querySelectorAll("summary"),
      ...canvasElement.querySelectorAll("footer a"),
    ].filter((target): target is Element => target instanceof Element);

    for (const target of touchTargets) {
      await expect(
        target.getBoundingClientRect().height,
      ).toBeGreaterThanOrEqual(44);
    }
    expect(document.documentElement.scrollWidth <= window.innerWidth).toBe(
      true,
    );
  },
};
