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
  document_id: "completed-document",
  error_code: null,
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
    if (documentId === "error-document") {
      return HttpResponse.json(
        { code: "document_reflow_not_scheduled", message: "not scheduled" },
        { status: 409 },
      );
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
        error_code: "document_reflow_failed",
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
  http.post(`${endpoint}/retries`, ({ params }) => {
    const documentId = String(params.documentId);
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
];

const meta = {
  title: "Reader/Reflow/ReaderReflowSurface",
  component: ReaderReflowSurface,
  args: {
    documentId: "completed-document",
    fullTranslationEnabled: false,
    onOutlineChange: fn(),
    onOpenPdfPage: fn(),
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
  parameters: { layout: "fullscreen", msw: { handlers } },
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

export const Unscheduled: Story = {
  args: { documentId: "error-document" },
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
