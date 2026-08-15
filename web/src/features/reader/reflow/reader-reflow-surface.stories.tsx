import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { delay, http, HttpResponse } from "msw";
import { expect, fn, userEvent, within } from "storybook/test";

import { ToastProvider } from "@/components/ui";
import { ReaderReflowSurface } from "./reader-reflow-surface";

const endpoint = "http://127.0.0.1:7301/api/v1/papers/:documentId/reflow";

const completed = {
  blocks: [
    {
      asset_id: null,
      group_id: null,
      heading_level: 1,
      id: "title",
      index: 0,
      kind: "title",
      presentation_status: "verbatim",
      render_markdown: "# A Responsive Reading Surface",
      source_spans: [
        {
          page_number: 1,
          source_rect: { height: 0.08, width: 0.72, x: 0.14, y: 0.2 },
          source_text: "A Responsive Reading Surface",
        },
      ],
    },
    {
      asset_id: null,
      group_id: null,
      heading_level: null,
      id: "paragraph",
      index: 1,
      kind: "paragraph",
      presentation_status: "verbatim",
      render_markdown:
        "This source paragraph remains exact while its reading layout adapts to the viewport.",
      source_spans: [
        {
          page_number: 1,
          source_rect: { height: 0.08, width: 0.72, x: 0.14, y: 0.32 },
          source_text:
            "This source paragraph remains exact while its reading layout adapts to the viewport.",
        },
      ],
    },
  ],
  assets: [],
  attempt_count: 1,
  document_id: "completed-document",
  failure: null,
  job_id: "10000000-0000-4000-8000-000000000001",
  parser_revision: "mineru-content-list-v1",
  pipeline_revision: "mineru-continuous-ast-v1",
  status: "completed",
  updated_at: "2026-08-14T00:00:00Z",
  warnings: [],
};

const retriedDocuments = new Set<string>();

const handlers = [
  http.get(endpoint, async ({ params }) => {
    const documentId = String(params.documentId);
    if (documentId === "slow-document") {
      await delay("infinite");
    }
    if (
      [
        "error-document",
        "credential-document",
        "invalid-credential-document",
      ].includes(documentId)
    ) {
      return HttpResponse.json({
        ...completed,
        attempt_count: 0,
        blocks: [],
        document_id: documentId,
        job_id: null,
        parser_revision: null,
        pipeline_revision: null,
        status: "not_requested",
        updated_at: null,
      });
    }
    if (documentId === "failed-document") {
      if (retriedDocuments.has(documentId)) {
        return HttpResponse.json({
          ...completed,
          blocks: [],
          document_id: documentId,
          parser_revision: null,
          pipeline_revision: null,
          status: "pending",
        });
      }
      return HttpResponse.json({
        ...completed,
        blocks: [],
        document_id: documentId,
        failure: {
          code: "document_reflow_failed",
          required_integration: null,
          retryable: true,
        },
        status: "failed",
      });
    }
    if (documentId === "rate-limited-document") {
      return HttpResponse.json({
        ...completed,
        blocks: [],
        document_id: documentId,
        failure: {
          code: "mineru_rate_limited",
          required_integration: null,
          retryable: true,
        },
        status: "failed",
      });
    }
    if (documentId === "unsafe-document") {
      return HttpResponse.json({
        ...completed,
        blocks: [],
        document_id: documentId,
        failure: {
          code: "mineru_response_unsafe",
          required_integration: null,
          retryable: false,
        },
        status: "failed",
      });
    }
    if (documentId === "processing-document") {
      return HttpResponse.json({
        ...completed,
        blocks: [],
        document_id: documentId,
        parser_revision: null,
        pipeline_revision: null,
        status: "processing",
      });
    }
    return HttpResponse.json({ ...completed, document_id: documentId });
  }),
  http.post(`${endpoint}/attempts`, ({ params }) => {
    const documentId = String(params.documentId);
    if (
      ["credential-document", "invalid-credential-document"].includes(
        documentId,
      )
    ) {
      return HttpResponse.json(
        {
          code:
            documentId === "credential-document"
              ? "mineru_credential_required"
              : "mineru_credential_invalid",
          kind: "unprocessable",
          message: "Connect MinerU",
          retryable: true,
        },
        { status: 422 },
      );
    }
    retriedDocuments.add(documentId);
    return HttpResponse.json(
      {
        ...completed,
        blocks: [],
        document_id: documentId,
        parser_revision: null,
        pipeline_revision: null,
        status: "pending",
      },
      { status: 202 },
    );
  }),
  http.get("http://127.0.0.1:7301/api/v1/me/integrations", () =>
    HttpResponse.json({
      items: [
        {
          category: "parsing",
          enabled: false,
          managed: false,
          provider: "mineru",
          state: "disconnected",
          updated_at: null,
          verified_at: null,
        },
      ],
    }),
  ),
];

const meta = {
  title: "Reader/Reflow/ReaderReflowSurface",
  component: ReaderReflowSurface,
  args: {
    documentId: "completed-document",
    fullTranslationEnabled: false,
    onOutlineChange: fn(),
    onOpenPdfSource: fn(),
    onTranslationStatusChange: fn(),
    preferences: {
      auto_translate_selection: true,
      custom_instructions: null,
      full_translation_display: "bilingual",
      show_translation_marker: true,
      source_language: "auto",
      target_language: "zh-CN",
      translate_references: false,
    },
    targetLanguage: "zh-CN",
    translationCacheVersion: "preferences-v1",
  },
  decorators: [
    (Story) => (
      <ToastProvider dismissLabel="Dismiss notification">
        <Story />
      </ToastProvider>
    ),
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof ReaderReflowSurface>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Completed: Story = {};

export const Processing: Story = {
  args: { documentId: "processing-document" },
};

export const Loading: Story = {
  args: { documentId: "slow-document" },
};

export const NotRequested: Story = {
  args: { documentId: "error-document" },
};

export const MinerURequired: Story = {
  args: { documentId: "credential-document" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Start AI reflow" }),
    );
    await expect(
      await canvas.findByRole("heading", {
        name: "Connect MinerU to use AI reflow",
      }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("link", { name: "Get a MinerU token" }),
    ).toHaveAttribute("href", "https://mineru.net/apiManage/token");
  },
};

export const MinerUInvalid: Story = {
  args: { documentId: "invalid-credential-document" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Start AI reflow" }),
    );
    await expect(
      await canvas.findByRole("heading", {
        name: "Connect MinerU to use AI reflow",
      }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Open Connections" }),
    ).toBeVisible();
  },
};

export const RateLimitedFailure: Story = {
  args: { documentId: "rate-limited-document" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(/rate limiting requests/i),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Retry AI reflow" }),
    ).toBeVisible();
  },
};

export const UnsafeFailure: Story = {
  args: { documentId: "unsafe-document" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(/unsafe or invalid archive/i),
    ).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "Retry AI reflow" }),
    ).not.toBeInTheDocument();
  },
};

export const FailedAndRetry: Story = {
  args: { documentId: "failed-document" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const retry = await canvas.findByRole("button", {
      name: "Retry AI reflow",
    });
    await userEvent.click(retry);
    await expect(
      await canvas.findByRole("status", { name: "Loading" }),
    ).toBeVisible();
  },
};
