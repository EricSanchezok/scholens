import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { fn } from "storybook/test";

import type { ReaderSelection } from "../components/pdf-page";
import type { TranslationPreferences } from "./api";
import { ReaderTranslationPanel } from "./reader-translation-panel";

const selection: ReaderSelection = {
  kind: "paper_selection",
  document_id: "10000000-0000-4000-8000-000000000001",
  page_number: 3,
  selected_text:
    "Retrieval quality depends on ranking, context construction, and the evidence available to the model.",
  anchor: {
    kind: "pdf_text",
    page_number: 3,
    rects: [{ x: 0.16, y: 0.28, width: 0.68, height: 0.04 }],
  },
};

const preferences: TranslationPreferences = {
  auto_translate_selection: true,
  custom_instructions: null,
  full_translation_display: "bilingual",
  show_translation_marker: true,
  source_language: "auto",
  target_language: "zh-CN",
  translate_references: false,
};

const meta = {
  title: "Reader/Translation panel",
  component: ReaderTranslationPanel,
  args: {
    onAnnotate: fn(),
    onPreferencesChange: fn(async () => preferences),
    onRetry: fn(),
    onTranslate: fn(),
    preferences,
    preferencesLoading: false,
    preferencesSaving: false,
    state: {
      cacheHit: false,
      retryable: false,
      status: "idle",
      translatedText: "",
    },
  },
  decorators: [
    (Story) => (
      <div className="bg-canvas mx-auto h-[44rem] w-[31.25rem] max-w-[100vw] border">
        <Story />
      </div>
    ),
  ],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ReaderTranslationPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {};

export const Ready: Story = {
  args: {
    state: {
      cacheHit: false,
      retryable: false,
      selection,
      status: "ready",
      translatedText: "",
    },
  },
};

export const Streaming: Story = {
  args: {
    state: {
      cacheHit: false,
      retryable: false,
      selection,
      status: "streaming",
      targetLanguage: "zh-CN",
      translatedText: "检索质量取决于排序、上下文构建，以及模型可以获得的",
      trigger: "auto",
    },
  },
};

export const CompletedAndCached: Story = {
  args: {
    state: {
      cacheHit: true,
      retryable: false,
      selection,
      status: "completed",
      targetLanguage: "zh-CN",
      translatedText:
        "检索质量取决于排序、上下文构建，以及模型可以获得的证据。",
      trigger: "manual",
    },
  },
};

export const QuotaExceeded: Story = {
  args: {
    state: {
      cacheHit: false,
      errorCode: "token_quota_exceeded",
      retryable: false,
      selection,
      status: "error",
      translatedText: "",
      trigger: "manual",
    },
  },
};

export const RetryableError: Story = {
  args: {
    state: {
      cacheHit: false,
      errorCode: "translation_provider_unavailable",
      retryable: true,
      selection,
      status: "error",
      translatedText: "",
      trigger: "manual",
    },
  },
};

export const EdgeBlocked: Story = {
  args: {
    state: {
      cacheHit: false,
      errorCode: "edge_blocked",
      retryable: false,
      selection,
      status: "error",
      translatedText: "",
      trigger: "manual",
    },
  },
};

export const NarrowMobile: Story = {
  ...Streaming,
  globals: { viewport: { value: "smallMobile" } },
};

export const CompletedDark: Story = {
  ...CompletedAndCached,
  globals: { appearance: "dark" },
};
