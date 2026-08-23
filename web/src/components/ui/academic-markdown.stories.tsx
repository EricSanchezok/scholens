import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, waitFor } from "storybook/test";

import { AcademicMarkdown } from "./academic-markdown";

const academicExample = [
  String.raw`Inline formulas support $E = mc^2$ and \(p(x \mid y)\).`,
  "",
  String.raw`Literal currency remains text when escaped: \$40.`,
  "",
  "$$",
  String.raw`\hat{y} = \sum_{i=1}^{n} \frac{a_i - \overline{x}}{\sqrt{\sigma^2}}`,
  "$$",
  "",
  String.raw`\[`,
  String.raw`\begin{bmatrix} a & b \\ c & d \end{bmatrix}`,
  String.raw`\]`,
  "",
  String.raw`Code stays literal: ` + "`" + String.raw`\(not_math\)` + "`.",
].join("\n");

const meta = {
  title: "Content/Academic Markdown",
  component: AcademicMarkdown,
  tags: ["autodocs"],
  parameters: { layout: "padded" },
  args: { children: academicExample },
  decorators: [
    (Story) => (
      <div className="text-foreground mx-auto max-w-2xl text-base leading-7 [&>*+*]:mt-5">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof AcademicMarkdown>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AllSyntax: Story = {
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelectorAll(".katex")).toHaveLength(4),
    );
    await expect(
      canvasElement.querySelectorAll(".katex-mathml math"),
    ).toHaveLength(4);
    await expect(
      canvasElement.querySelectorAll(".katex-html[aria-hidden='true']"),
    ).toHaveLength(4);
    await expect(canvasElement.textContent).toContain("$40");
    await expect(canvasElement.textContent).toContain("\\(not_math\\)");
  },
};

export const AllSyntaxDark: Story = {
  ...AllSyntax,
  globals: { appearance: "dark" },
};

export const NarrowWideEquation: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  args: {
    children: String.raw`\[
\mathcal{L}(\theta) = \prod_{t=1}^{T} p\left(x_t \mid x_{<t}, \theta\right) \cdot \prod_{s=1}^{S} q\left(z_s \mid z_{<s}, \theta\right)
\]`,
  },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelector(".katex-display")).not.toBeNull(),
    );
    const display = canvasElement.querySelector<HTMLElement>(".katex-display");
    if (!display) return;
    await expect(display).toHaveAttribute("tabindex", "0");
    await expect(display.scrollWidth).toBeGreaterThan(display.clientWidth);
    await expect(getComputedStyle(display).overflowY).not.toBe("hidden");
    await expect(
      parseFloat(getComputedStyle(display).paddingTop),
    ).toBeGreaterThan(0);
  },
};

export const IncompleteStreamingFormula: Story = {
  args: { children: String.raw`The model is still writing \(x^2 +` },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".katex")).toBeNull();
    await expect(canvasElement.textContent).toContain("(x^2 +");
  },
};
