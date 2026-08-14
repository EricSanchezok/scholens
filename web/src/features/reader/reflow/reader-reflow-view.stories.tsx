import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import * as React from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import {
  ReaderReflowView,
  type ReaderReflowLabels,
} from "./reader-reflow-view";

const labels: ReaderReflowLabels = {
  document: "AI-reflowed paper",
  figurePlaceholder: "Figure",
  fullTranslation: "Full translation",
  fullTranslationDescription:
    "Translate nearby sections as you read. Completed sections are cached.",
  openPdfPage: (page) => `PDF p. ${page}`,
  original: "Original text",
  retryTranslation: "Retry translation",
  translated: "Translated text",
  translating: "Translating this section…",
  translationFailed: "This section could not be translated.",
};

const blocks = [
  {
    heading_level: 1,
    id: "title",
    index: 0,
    kind: "title" as const,
    page_number: 1,
    source_markdown:
      "# LitSearch: A Retrieval Benchmark for Scientific Literature Search",
  },
  {
    heading_level: null,
    id: "authors",
    index: 1,
    kind: "authors" as const,
    page_number: 1,
    source_markdown:
      "Anirudh Ajith · Mengzhou Xia · Alexis Chevalier · Tanya Goyal",
  },
  {
    heading_level: 2,
    id: "abstract",
    index: 2,
    kind: "heading" as const,
    page_number: 1,
    source_markdown: "## Abstract",
  },
  {
    heading_level: null,
    id: "paragraph",
    index: 3,
    kind: "paragraph" as const,
    page_number: 1,
    source_markdown:
      "Literature search questions often require a deep understanding of research concepts and the ability to reason across entire articles. We introduce **LitSearch**, a retrieval benchmark comprising 597 realistic queries about recent ML and NLP papers.",
  },
  {
    heading_level: 2,
    id: "method",
    index: 4,
    kind: "heading" as const,
    page_number: 3,
    source_markdown: "## 1 Introduction",
  },
  {
    heading_level: null,
    id: "table",
    index: 5,
    kind: "table" as const,
    page_number: 4,
    source_markdown:
      "| Retriever | Recall@5 |\n| --- | ---: |\n| BM25 | 42.1 |\n| Dense | 66.9 |",
  },
];

const translated = {
  abstract: {
    cacheHit: true,
    status: "completed" as const,
    text: "## 摘要",
  },
  authors: {
    cacheHit: true,
    status: "completed" as const,
    text: "Anirudh Ajith · Mengzhou Xia · Alexis Chevalier · Tanya Goyal",
  },
  paragraph: {
    cacheHit: false,
    status: "completed" as const,
    text: "文献检索问题通常需要深入理解研究概念，并具备对整篇文章进行推理的能力。我们提出了 **LitSearch**：一个包含 597 个近期机器学习与自然语言处理论文真实查询的检索基准。",
  },
  title: {
    cacheHit: true,
    status: "completed" as const,
    text: "# LitSearch：面向科学文献检索的检索基准",
  },
};

const meta = {
  title: "Reader/Reflow/ReaderReflowView",
  component: ReaderReflowView,
  args: {
    blocks,
    fullTranslationEnabled: false,
    labels,
    onFullTranslationEnabledChange: fn(),
    onOpenPdfPage: fn(),
    onRequestTranslation: fn(),
    onRetryTranslation: fn(),
    title: "LitSearch",
    targetLanguage: "zh-CN",
    translations: {},
  },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ReaderReflowView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Original: Story = {};

export const Translated: Story = {
  args: { fullTranslationEnabled: true, translations: translated },
};

export const Streaming: Story = {
  args: {
    fullTranslationEnabled: true,
    translations: {
      ...translated,
      method: { status: "streaming", text: "## 1 引言" },
      table: { status: "queued", text: "" },
    },
  },
};

export const TranslationError: Story = {
  args: {
    fullTranslationEnabled: true,
    translations: {
      paragraph: {
        errorCode: "translation_provider_unavailable",
        retryable: true,
        status: "error",
        text: "文献检索问题通常需要深入理解研究概念。",
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("文献检索问题通常需要深入理解研究概念。"),
    ).toBeVisible();
    await expect(
      canvas.getByText("This section could not be translated."),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Retry translation" }),
    ).toBeVisible();
  },
};

export const Mobile: Story = {
  args: { fullTranslationEnabled: true, translations: translated },
  globals: { viewport: { value: "mobile" } },
};

export const Dark: Story = {
  args: { fullTranslationEnabled: true, translations: translated },
  globals: { appearance: "dark" },
};

export const InteractiveToggle: Story = {
  render: (args) => {
    function Harness() {
      const [enabled, setEnabled] = React.useState(false);
      return (
        <ReaderReflowView
          {...args}
          fullTranslationEnabled={enabled}
          onFullTranslationEnabledChange={setEnabled}
          translations={enabled ? translated : {}}
        />
      );
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = canvas.getByRole("switch", { name: "Full translation" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect(
      canvas.getByText("LitSearch：面向科学文献检索的检索基准"),
    ).toBeVisible();
  },
};
