import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, within } from "storybook/test";

import type { ReaderSelection } from "./pdf-page";
import {
  ReaderAnnotationPanel,
  ReaderDetailsPanel,
} from "./reader-context-panel";
import type { ReaderAnnotation, ReaderDocument } from "../reader-types";

const selection: ReaderSelection = {
  kind: "paper_selection",
  document_id: "10000000-0000-4000-8000-000000000001",
  page_number: 4,
  selected_text:
    "Retrieval quality depends on the relationship between chunking, ranking, and context construction.",
  anchor: {
    kind: "pdf_text",
    page_number: 4,
    rects: [{ x: 0.1, y: 0.2, width: 0.7, height: 0.04 }],
  },
};

const annotation: ReaderAnnotation = {
  id: "20000000-0000-4000-8000-000000000001",
  kind: "highlight_thread",
  scope_type: "document",
  scope_id: selection.document_id,
  is_shared: false,
  created_at: "2026-08-12T10:00:00Z",
  updated_at: "2026-08-12T10:00:00Z",
  created_by: { id: 1, display_name: "Eric" },
  capabilities: { delete: true, edit: true, share: false },
  highlight_thread: {
    color: "yellow",
    quote_text: selection.selected_text,
    role: "note",
    position: selection.anchor,
    comments: [
      {
        id: "30000000-0000-4000-8000-000000000001",
        thread_id: "20000000-0000-4000-8000-000000000001",
        content: "Compare this claim with the evaluation section.",
        role: "user",
        created_at: "2026-08-12T10:01:00Z",
        updated_at: "2026-08-12T10:01:00Z",
        created_by: { id: 1, display_name: "Eric" },
        can_edit: true,
        can_delete: true,
      },
    ],
  },
};

const document: ReaderDocument = {
  document_id: selection.document_id,
  title: "Retrieval-Augmented Generation: Foundations and Open Questions",
  original_filename: "rag-foundations.pdf",
  mime_type: "application/pdf",
  size_bytes: 2_621_440,
  processing_status: "completed",
  created_at: "2026-08-12T09:00:00Z",
  updated_at: "2026-08-12T09:02:00Z",
  authors: ["A. Researcher", "B. Scholar"],
  abstract: "A review of retrieval-augmented generation systems.",
  summary: "The paper connects retrieval, ranking, and context construction.",
  summary_citations: null,
  starter_questions: null,
  doi: "10.1000/rag.2026",
  institutions: ["Scholens Research"],
  journal: "Journal of Research Systems",
  keywords: ["retrieval", "language models"],
  parser_quality: "high",
  parser_warning_code: null,
  publish_date: "2026-06-01",
  publisher: "Scholens Press",
};

const annotationArgs = {
  annotations: [annotation],
  error: false,
  onActionError: fn(),
  onCommentCreate: fn(async () => undefined),
  onCommentDelete: fn(async () => undefined),
  onCommentUpdate: fn(async () => undefined),
  onCreate: fn(async () => undefined),
  onDelete: fn(async () => undefined),
  onSelect: fn(),
  onUpdateColor: fn(async () => undefined),
};

const meta = {
  title: "Reader/Context panels",
  component: ReaderAnnotationPanel,
  args: annotationArgs,
  decorators: [
    (Story) => (
      <div className="bg-canvas min-h-[42rem] w-[23rem] max-w-full border-l">
        <Story />
      </div>
    ),
  ],
  parameters: { layout: "centered" },
} satisfies Meta<typeof ReaderAnnotationPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AnnotationThread: Story = {
  args: { selectedAnnotation: annotation },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText(/Retrieval quality depends/),
    ).toBeVisible();
  },
};

export const SelectionReady: Story = {
  args: { annotations: [], selection },
};

export const EmptyAnnotations: Story = {
  args: { annotations: [] },
};

export const NarrowSelection: Story = {
  args: { annotations: [], selection },
  globals: { viewport: { value: "smallMobile" } },
};

export const Details: Story = {
  render: () => (
    <ReaderDetailsPanel document={document} title={document.title!} />
  ),
};
