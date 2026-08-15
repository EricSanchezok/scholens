import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, within } from "storybook/test";

import type { DocumentReflowBlock } from "./api";
import {
  ReaderReflowView,
  type ReaderReflowLabels,
} from "./reader-reflow-view";

const labels: ReaderReflowLabels = {
  degradedDescription:
    "This content cannot be reconstructed reliably without guessing.",
  degradedTitle: "Could not reflow reliably",
  document: "AI-reflowed paper",
  figurePlaceholder: "Figure",
  openPdfPage: (page) => `PDF p. ${page}`,
  original: "Original text",
  paperInformation: "Paper information",
  repaired: "AI-assisted repair",
  retryTranslation: "Retry translation",
  translated: "Translated text",
  translationFailed: "This section could not be translated.",
  translationMarker: "Translation",
};

function block(
  id: string,
  kind: DocumentReflowBlock["kind"],
  source: string,
  overrides: Partial<DocumentReflowBlock> = {},
): DocumentReflowBlock {
  return {
    asset_id: null,
    group_id: null,
    heading_level: kind === "heading" ? 2 : null,
    id,
    index: 0,
    kind,
    presentation_status: "verbatim",
    render_markdown: source,
    source_spans: [
      {
        page_number: 1,
        source_rect: { height: 0.08, width: 0.72, x: 0.14, y: 0.2 },
        source_text: source,
      },
    ],
    ...overrides,
  };
}

const blocks: DocumentReflowBlock[] = [
  block("eyebrow", "eyebrow", "Research article", { index: 0 }),
  block(
    "title",
    "title",
    "# LitSearch: A Retrieval Benchmark for Scientific Literature Search",
    { heading_level: 1, index: 1 },
  ),
  block(
    "authors",
    "authors",
    "Anirudh Ajith<sup>1</sup> · Mengzhou Xia<sup>2</sup>",
    { index: 2 },
  ),
  block(
    "affiliations",
    "affiliations",
    "1 Carnegie Mellon University  \\n2 Princeton University",
    { index: 3 },
  ),
  block(
    "abstract",
    "abstract",
    "**Abstract.** Literature search requires reasoning across entire papers.",
    { index: 4 },
  ),
  block("keywords", "keywords", "**Keywords:** retrieval, evaluation", {
    index: 5,
  }),
  block("introduction", "heading", "## 1 Introduction", {
    index: 6,
  }),
  block(
    "paragraph",
    "paragraph",
    "We introduce **LitSearch**, a benchmark with 597 realistic queries and deterministic evidence links.",
    { index: 7 },
  ),
  block("list", "list", "- Natural queries\n- Expert-reviewed evidence", {
    index: 8,
  }),
  block("quote", "quote", "> Evidence must remain traceable to the PDF.", {
    index: 9,
  }),
  block("equation", "equation", "$$R@5 = \\frac{|D_5 \\cap G|}{|G|}$$", {
    index: 10,
  }),
  block(
    "table",
    "table",
    "| Retriever | Recall@5 |\n| --- | ---: |\n| BM25 | 42.1 |\n| Dense | 66.9 |",
    { index: 11 },
  ),
  block("figure", "figure", "Figure 1. Retrieval evaluation pipeline", {
    index: 12,
  }),
  block("caption", "caption", "Figure 1: The evaluation pipeline.", {
    index: 13,
  }),
  block("code", "code", "```python\nscore = recall(results, gold)\n```", {
    index: 14,
  }),
  block("footnote", "footnote", "1. Authors contributed equally.", {
    index: 15,
  }),
  block("references", "references", "## References\nAjith et al. (2026).", {
    index: 16,
    source_spans: [
      {
        page_number: 12,
        source_rect: { height: 0.08, width: 0.72, x: 0.14, y: 0.2 },
        source_text: "References Ajith et al. (2026).",
      },
    ],
  }),
];

const translated = {
  abstract: {
    cacheHit: true,
    status: "completed" as const,
    text: "**摘要。** 文献检索需要对整篇论文进行推理。",
  },
  introduction: {
    cacheHit: true,
    status: "completed" as const,
    text: "## 1 引言",
  },
  paragraph: {
    cacheHit: false,
    status: "completed" as const,
    text: "我们提出 **LitSearch**：一个包含 597 个真实查询并保留确定性证据链接的基准。",
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
    assets: [],
    blocks,
    documentId: "10000000-0000-4000-8000-000000000001",
    fullTranslationDisplay: "bilingual",
    fullTranslationEnabled: false,
    labels,
    onOpenPdfSource: fn(),
    onRequestTranslation: fn(),
    onRetryTranslation: fn(),
    showTranslationMarker: true,
    targetLanguage: "zh-CN",
    translateReferences: false,
    translations: {},
  },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ReaderReflowView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AcademicStructure: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Paper information")).toBeVisible();
    await expect(canvasElement.textContent).not.toContain("<sup>");
    await expect(canvasElement.querySelector(".katex")).not.toBeNull();
  },
};

export const Bilingual: Story = {
  args: { fullTranslationEnabled: true, translations: translated },
};

export const TranslationOnly: Story = {
  args: {
    fullTranslationDisplay: "translation_only",
    fullTranslationEnabled: true,
    translations: translated,
  },
};

export const Streaming: Story = {
  args: {
    fullTranslationEnabled: true,
    translations: {
      ...translated,
      list: { status: "queued", text: "" },
      quote: { status: "streaming", text: "证据必须" },
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
      canvas.getByText("This section could not be translated."),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Retry translation" }),
    ).toBeVisible();
  },
};

export const DegradedEvidence: Story = {
  args: {
    blocks: [
      block("damaged-table", "table", "untrusted reconstructed table", {
        presentation_status: "degraded",
      }),
    ],
  },
};

export const SmallMobile: Story = {
  args: { fullTranslationEnabled: true, translations: translated },
  globals: { viewport: { value: "smallMobile" } },
};

export const LargeMobile: Story = {
  args: { fullTranslationEnabled: true, translations: translated },
  globals: { viewport: { value: "largeMobile" } },
};

export const Dark: Story = {
  args: { fullTranslationEnabled: true, translations: translated },
  globals: { appearance: "dark" },
};
