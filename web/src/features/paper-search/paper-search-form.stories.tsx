import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import * as React from "react";
import { expect, userEvent, within } from "storybook/test";

import { PaperSearchForm } from "./paper-search-form";

function ControlledPaperSearchForm() {
  const [committedQuery, setCommittedQuery] = React.useState("");
  const [draft, setDraft] = React.useState("");
  return (
    <div className="mx-auto w-full max-w-2xl p-6">
      <PaperSearchForm
        committedQuery={committedQuery}
        draft={draft}
        label="Search papers"
        onCommit={setCommittedQuery}
        onDraftChange={setDraft}
      />
      <p className="text-secondary mt-4 text-sm">
        {committedQuery || "No committed query"}
      </p>
    </div>
  );
}

const meta = {
  title: "Features/Paper Search/Submit Form",
  component: ControlledPaperSearchForm,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ControlledPaperSearchForm>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DraftThenSubmit: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const search = canvas.getByRole("searchbox", { name: "Search papers" });

    await userEvent.type(search, "code world");
    await expect(canvas.getByText("No committed query")).toBeVisible();
    await expect(search).toHaveValue("code world");

    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByText("code world")).toBeVisible();
    await expect(search).toHaveFocus();
  },
};

export const InvalidChinese: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const search = canvas.getByRole("searchbox", { name: "Search papers" });

    await userEvent.type(search, "码{Enter}");
    await expect(
      canvas.getByText("请输入至少 2 个字符，或清空输入框以显示全部论文。"),
    ).toBeVisible();
    await expect(search).toHaveAccessibleDescription(
      "请输入至少 2 个字符，或清空输入框以显示全部论文。",
    );
  },
};
