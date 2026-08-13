import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { ReaderSelection } from "./pdf-page";
import {
  ReaderAnnotationPanel,
  ReaderConversationSwitcher,
  ReaderDetailsPanel,
} from "./reader-context-panel";
import type {
  ReaderAnnotation,
  ReaderAnnotationSummary,
  ReaderConversation,
  ReaderDocument,
} from "../reader-types";

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
  kind: "annotation_thread",
  audience: { kind: "personal" },
  target_document_id: selection.document_id,
  created_at: "2026-08-12T10:00:00Z",
  updated_at: "2026-08-12T10:00:00Z",
  created_by: { id: 1, display_name: "Eric" },
  capabilities: { delete: true, edit: true },
  annotation_thread: {
    capabilities: {
      delete: true,
      recolor: true,
      reopen: false,
      reply: true,
      resolve: false,
    },
    color: "yellow",
    comment_count: 1,
    quote_text: selection.selected_text,
    last_activity_at: "2026-08-12T10:01:00Z",
    mode: "note",
    role: "note",
    status: "open",
    resolved_at: null,
    resolved_by: null,
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

const projectAnnotation: ReaderAnnotation = {
  ...annotation,
  id: "20000000-0000-4000-8000-000000000002",
  audience: {
    kind: "project",
    project_id: "50000000-0000-4000-8000-000000000001",
  },
  created_by: { id: 2, display_name: "Mina" },
  annotation_thread: {
    ...annotation.annotation_thread!,
    color: "blue",
    comment_count: 2,
    capabilities: {
      delete: false,
      recolor: false,
      reopen: false,
      reply: true,
      resolve: true,
    },
    last_activity_at: "2026-08-12T10:04:00Z",
    mode: "discussion",
    comments: [
      ...annotation.annotation_thread!.comments,
      {
        id: "30000000-0000-4000-8000-000000000002",
        thread_id: "20000000-0000-4000-8000-000000000002",
        content: "I found a contrasting result in section seven.",
        role: "user",
        created_at: "2026-08-12T10:04:00Z",
        updated_at: "2026-08-12T10:04:00Z",
        created_by: { id: 2, display_name: "Mina" },
        can_edit: false,
        can_delete: false,
      },
    ],
  },
};

function annotationSummary(item: ReaderAnnotation): ReaderAnnotationSummary {
  const thread = item.annotation_thread;
  if (!thread || !item.target_document_id) {
    throw new Error("Story annotation requires a document thread");
  }
  if (item.audience.kind === "document") {
    throw new Error("Reader annotations cannot use a document audience");
  }
  return {
    audience: item.audience,
    capabilities: thread.capabilities,
    color: thread.color,
    comment_count: thread.comment_count,
    comments: thread.comments,
    created_at: item.created_at,
    created_by: item.created_by,
    id: item.id,
    last_activity_at: thread.last_activity_at,
    mode: thread.mode,
    position: thread.position,
    quote_text: thread.quote_text,
    resolved_at: thread.resolved_at,
    resolved_by: thread.resolved_by,
    role: thread.role,
    status: thread.status,
    target_document_id: item.target_document_id,
  };
}

const personalSummary = annotationSummary(annotation);
const projectSummary = annotationSummary(projectAnnotation);

const resolvedAnnotation: ReaderAnnotation = {
  ...projectAnnotation,
  id: "20000000-0000-4000-8000-000000000003",
  annotation_thread: {
    ...projectAnnotation.annotation_thread!,
    status: "resolved",
    resolved_at: "2026-08-12T11:00:00Z",
    resolved_by: { id: 1, display_name: "Eric" },
    capabilities: {
      ...projectAnnotation.annotation_thread!.capabilities,
      reply: false,
      resolve: false,
      reopen: true,
    },
  },
};
const resolvedSummary = annotationSummary(resolvedAnnotation);

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

const conversations: ReaderConversation[] = [
  {
    id: "40000000-0000-4000-8000-000000000001",
    archived_at: null,
    capabilities: {
      archive: true,
      delete: true,
      detach: false,
      move: false,
      pin: true,
      rename: true,
      send: true,
      share: false,
    },
    pinned_at: "2026-08-12T10:05:00Z",
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: selection.document_id,
    scope_label: document.title,
    scope_type: "paper",
    title: "Compare the evaluation methods",
    updated_at: "2026-08-12T10:05:00Z",
  },
  {
    id: "40000000-0000-4000-8000-000000000002",
    archived_at: null,
    capabilities: {
      archive: true,
      delete: true,
      detach: false,
      move: false,
      pin: true,
      rename: true,
      send: true,
      share: false,
    },
    pinned_at: null,
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: selection.document_id,
    scope_label: document.title,
    scope_type: "paper",
    title: "Summarize the central contribution",
    updated_at: "2026-08-12T09:05:00Z",
  },
];

const annotationArgs = {
  audienceFilter: "all" as const,
  annotations: [personalSummary],
  error: false,
  onActionError: fn(),
  onCommentCreate: fn(async () => undefined),
  onCommentDelete: fn(async () => undefined),
  onCommentUpdate: fn(async () => undefined),
  onCreate: fn(async () => undefined),
  onDelete: fn(async () => undefined),
  onAudienceFilterChange: fn(),
  modeFilter: "all" as const,
  onModeFilterChange: fn(),
  onPreviewChange: fn(),
  onSelect: fn(),
  onStatusChange: fn(async () => undefined),
  onStatusFilterChange: fn(),
  onUpdateColor: fn(async () => undefined),
  statusFilter: "open" as const,
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
  args: { selectedAnnotationId: annotation.id },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const card = canvasElement.querySelector(
      `[data-reader-annotation-card="${annotation.id}"]`,
    );
    await expect(card).not.toBeNull();
    await userEvent.hover(card!);
    await expect(args.onPreviewChange).toHaveBeenLastCalledWith(annotation.id);
    await expect(
      card!.querySelector("[data-reader-annotation-quote]"),
    ).toHaveClass("truncate");
    await expect(
      canvas.queryByRole("button", { name: "Resolve" }),
    ).not.toBeInTheDocument();
    await userEvent.type(
      canvas.getByPlaceholderText("Continue this note"),
      "A compact follow-up{enter}",
    );
    await expect(args.onCommentCreate).toHaveBeenCalledWith(
      annotation.id,
      "A compact follow-up",
    );
  },
};

export const AnnotationPaletteDark: Story = {
  args: { selectedAnnotationId: annotation.id },
  globals: { appearance: "dark" },
};

export const ProjectDiscussionTwoAuthors: Story = {
  args: {
    annotations: [projectSummary],
    projectContext: {
      id: "50000000-0000-4000-8000-000000000001",
      title: "Agentic Web review",
    },
    selectedAnnotationId: projectAnnotation.id,
  },
};

export const ProjectDiscussionChinese: Story = {
  ...ProjectDiscussionTwoAuthors,
  globals: { locale: "zh-CN" },
};

export const ProjectDiscussionLongContent: Story = {
  args: {
    ...ProjectDiscussionTwoAuthors.args,
    annotations: [
      {
        ...projectSummary,
        quote_text:
          `${projectSummary.quote_text} ` +
          "The authors then connect this retrieval constraint to evaluation design, deployment cost, and the limits of generalizing from a single benchmark across domains.",
        comments: projectSummary.comments.map((comment, index) => ({
          ...comment,
          content:
            index === 0
              ? `${comment.content} Please also trace the evidence through the ablation table and record whether the claimed improvement remains significant across every reported dataset.`
              : comment.content,
        })),
      },
    ],
    selectedAnnotationId: projectAnnotation.id,
  },
  play: async ({ canvasElement }) => {
    const panel = canvasElement.querySelector<HTMLElement>(
      "[data-reader-annotation-panel]",
    );
    const quote = canvasElement.querySelector<HTMLElement>(
      "[data-reader-annotation-quote]",
    );
    await expect(panel).not.toBeNull();
    await expect(quote).not.toBeNull();
    await expect(quote).toHaveClass("truncate");
    await expect(quote!.scrollWidth).toBeGreaterThan(quote!.clientWidth);
    await expect(panel!.scrollWidth).toBe(panel!.clientWidth);
  },
};

export const ResolvedProjectDiscussion: Story = {
  args: {
    annotations: [resolvedSummary],
    projectContext: {
      id: "50000000-0000-4000-8000-000000000001",
      title: "Agentic Web review",
    },
    selectedAnnotationId: resolvedAnnotation.id,
    statusFilter: "resolved",
  },
};

export const CommentlessPersonalHighlight: Story = {
  args: {
    annotations: [
      {
        ...personalSummary,
        comment_count: 0,
        comments: [],
        mode: "highlight",
        capabilities: {
          ...personalSummary.capabilities,
          resolve: false,
        },
      },
    ],
  },
};

export const ReadOnlyProjectDiscussion: Story = {
  args: {
    annotations: [
      {
        ...projectSummary,
        capabilities: {
          delete: false,
          recolor: false,
          reopen: false,
          reply: false,
          resolve: false,
        },
      },
    ],
    projectContext: {
      id: "50000000-0000-4000-8000-000000000001",
      title: "Agentic Web review",
    },
    selectedAnnotationId: projectAnnotation.id,
  },
};

export const NarrowProjectDiscussion: Story = {
  ...ProjectDiscussionTwoAuthors,
  globals: { viewport: { value: "smallMobile" } },
};

export const SelectionReady: Story = {
  args: { annotationSelection: selection, annotations: [] },
};

export const EmptyAnnotations: Story = {
  args: { annotations: [] },
};

export const NarrowSelection: Story = {
  args: { annotationSelection: selection, annotations: [] },
  globals: { viewport: { value: "smallMobile" } },
};

export const Details: Story = {
  render: () => (
    <ReaderDetailsPanel document={document} title={document.title!} />
  ),
};

export const ConversationSwitcherClosed: Story = {
  render: () => (
    <ReaderConversationSwitcher
      activeId={conversations[0]!.id}
      conversations={conversations}
      loading={false}
      onChange={fn()}
      onNew={fn()}
      onPin={fn(async () => undefined)}
      onPinError={fn()}
    />
  ),
};

export const ConversationSwitcherOpen: Story = {
  render: () => (
    <ReaderConversationSwitcher
      activeId={conversations[0]!.id}
      conversations={conversations}
      loading={false}
      onChange={fn()}
      onNew={fn()}
      onPin={fn(async () => undefined)}
      onPinError={fn()}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByPlaceholderText("Search this paper’s conversations"),
    ).not.toBeInTheDocument();
    const trigger = canvas.getByRole("button", {
      name: "Compare the evaluation methods",
    });
    await userEvent.click(trigger);
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
  },
};
