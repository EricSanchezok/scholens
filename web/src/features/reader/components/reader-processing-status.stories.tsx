import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ReaderProcessingStatus } from "./reader-processing-status";

const meta = {
  title: "Reader/ProcessingStatus",
  component: ReaderProcessingStatus,
  args: {
    onConnect: fn(),
    onRefresh: fn(),
    onRetry: fn(),
    stages: [
      {
        stage: "index",
        status: "completed",
        can_retry: false,
      },
      {
        stage: "enrichment",
        status: "running",
        job_id: "enrichment-job",
        can_retry: false,
      },
      {
        stage: "bibliography",
        status: "pending",
        job_id: "bibliography-job",
        can_retry: false,
      },
    ],
  },
} satisfies Meta<typeof ReaderProcessingStatus>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Working: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const summary = canvas.getByText(
      "Ready to read · Background work in progress",
    );
    await userEvent.click(summary);
    await expect(canvas.getByText("Queued")).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "Retry stage" }),
    ).not.toBeInTheDocument();
  },
};
export const Failed: Story = {
  args: {
    stages: [
      { stage: "index", status: "completed", can_retry: false },
      {
        stage: "enrichment",
        status: "failed",
        job_id: "enrichment-job",
        can_retry: true,
        required_integration: "deepseek",
      },
      { stage: "bibliography", status: "completed", can_retry: false },
    ],
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText("Details"));
    await expect(
      canvas.getByText(/even if the previous result was lost/),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect DeepSeek" }),
    );
    await expect(args.onConnect).toHaveBeenCalledOnce();
    await userEvent.click(
      canvas.getByRole("button", { name: "Retry AI with provider charges" }),
    );
    await expect(args.onRetry).toHaveBeenCalledWith(args.stages![1]);
  },
};
export const Retrying: Story = {
  args: { ...Failed.args, retrying: "enrichment-job" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText("Details"));
    await expect(
      canvas.getByRole("button", { name: "Retry AI with provider charges" }),
    ).toBeDisabled();
  },
};
export const RetryFailed: Story = {
  args: {
    ...Failed.args,
    retryError:
      "Retry was not confirmed. Refresh the status or try again. (request-123)",
  },
};
export const Ready: Story = {
  args: {
    stages: ["index", "enrichment", "bibliography"].map((stage) => ({
      stage: stage as "index" | "enrichment" | "bibliography",
      status: "completed",
      can_retry: false,
    })),
  },
};
export const Loading: Story = { args: { stages: undefined } };
export const Unavailable: Story = {
  args: { stages: undefined, unavailable: true },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText("Details"));
    await userEvent.click(
      canvas.getByRole("button", { name: "Refresh status" }),
    );
    await expect(args.onRefresh).toHaveBeenCalledOnce();
  },
};
export const NarrowChinese: Story = {
  args: Failed.args,
  globals: {
    locale: "zh-CN",
    viewport: { value: "smallMobile" },
    appearance: "dark",
  },
};
