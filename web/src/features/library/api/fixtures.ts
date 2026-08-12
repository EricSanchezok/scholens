import type { components } from "@/lib/api/generated/schema";

type Conversation = components["schemas"]["ConversationSummaryResponse"];
type LibraryOutput = components["schemas"]["LibraryOutputResponse"];
type LibraryPaper = components["schemas"]["LibraryPaperListPaperEntry"];
type LibraryPaperIngestion =
  components["schemas"]["LibraryPaperIngestionResponse"];
type Tag = components["schemas"]["LibraryTagResponse"];

const now = "2026-08-11T08:00:00Z";

export const libraryTags: Tag[] = [
  {
    id: "71000000-0000-4000-8000-000000000001",
    name: "Transformers",
    color: null,
  },
  {
    id: "71000000-0000-4000-8000-000000000002",
    name: "Retrieval",
    color: null,
  },
  {
    id: "71000000-0000-4000-8000-000000000003",
    name: "To review",
    color: null,
  },
];

function paper(
  id: string,
  title: string,
  authors: string[],
  publishDate: string,
  tags: Tag[] = [],
): LibraryPaper {
  return {
    created_at: now,
    document: {
      abstract: null,
      authors,
      created_at: now,
      document_id: id,
      doi: null,
      institutions: ["Scholens Research Lab"],
      journal: null,
      keywords: null,
      mime_type: "application/pdf",
      original_filename: `${title}.pdf`,
      parser_quality: "high",
      parser_warning_code: null,
      processing_status: "completed",
      publish_date: publishDate,
      publisher: null,
      size_bytes: 1_280_000,
      starter_questions: null,
      summary: null,
      summary_citations: null,
      title,
      updated_at: now,
    },
    entry_type: "paper",
    is_public: false,
    last_accessed_at: now,
    library_entry_id: id.replace("70000000", "72000000"),
    metadata_overrides: {},
    preview_url: null,
    status: "reading",
    tags,
    updated_at: now,
    user_id: 7,
  };
}

export const libraryPapers: LibraryPaper[] = [
  paper(
    "70000000-0000-4000-8000-000000000001",
    "Attention Is All You Need",
    ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
    "2017-06-12",
    [libraryTags[0]!],
  ),
  paper(
    "70000000-0000-4000-8000-000000000002",
    "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    ["Patrick Lewis", "Ethan Perez"],
    "2020-05-22",
    [libraryTags[1]!, libraryTags[2]!],
  ),
  paper(
    "70000000-0000-4000-8000-000000000003",
    "Constitutional AI: Harmlessness from AI Feedback",
    ["Yuntao Bai"],
    "2022-12-15",
  ),
];

export const libraryLongTitlePapers: LibraryPaper[] = libraryPapers.map(
  (item, index) => ({
    ...item,
    document: {
      ...item.document,
      title:
        index === 0
          ? "Holos: A Web-Scale LLM-Based Multi-Agent System for Open-Ended Scientific Collaboration"
          : index === 1
            ? "面向开放式科研协作与长期知识积累的超大规模多智能体系统研究"
            : item.document.title,
    },
  }),
);

const outputBase = {
  capabilities: { delete: true, edit: true, share: true },
  created_at: now,
  created_by: { display_name: "Eric", id: 7 },
  is_shared: false,
  updated_at: now,
};

export const libraryOutputs: LibraryOutput[] = [
  {
    item: {
      ...outputBase,
      highlight_thread: {
        color: "yellow",
        comments: [],
        position: {
          end_offset: 148,
          kind: "parsed_text",
          page_number: 6,
          start_offset: 64,
        },
        quote_text:
          "Self-attention connects all positions with a constant number of sequential operations.",
        role: "owner",
      },
      id: "76000000-0000-4000-8000-000000000001",
      kind: "highlight_thread",
      scope_id: libraryPapers[0]!.document.document_id,
      scope_type: "document",
    },
    source: {
      scope_id: libraryPapers[0]!.document.document_id,
      scope_type: "document",
      title: "Attention Is All You Need",
    },
    title: "Architecture notes",
  },
  {
    item: {
      ...outputBase,
      citation: {
        snapshot: {
          data: {
            authors: ["Ashish Vaswani", "Noam Shazeer"],
            document_id: libraryPapers[0]!.document.document_id,
            publish_date: "2017-06-12",
            title: "Attention Is All You Need",
          },
          document_id: libraryPapers[0]!.document.document_id,
          kind: "citation",
          method: "deterministic",
          preferred_style: "apa",
          style_display: "APA 7th",
        },
      },
      id: "76000000-0000-4000-8000-000000000002",
      kind: "citation",
      scope_id: null,
      scope_type: "personal",
    },
    source: { scope_id: null, scope_type: "personal", title: "My library" },
    title: "Transformer citation",
  },
  {
    item: {
      ...outputBase,
      audio_overview: {
        audio_url: "https://example.org/audio/retrieval-overview.mp3",
        citations: [],
        model_version: "overview-v1",
        title: "Retrieval methods overview",
        transcript:
          "A concise comparison of dense and sparse retrieval methods.",
        voice_id: "scholens-neutral",
      },
      id: "76000000-0000-4000-8000-000000000003",
      kind: "audio_overview",
      scope_id: "73000000-0000-4000-8000-000000000001",
      scope_type: "project",
    },
    source: {
      scope_id: "73000000-0000-4000-8000-000000000001",
      scope_type: "project",
      title: "Thesis literature review",
    },
    title: "Retrieval methods overview",
  },
  {
    item: {
      ...outputBase,
      data_table: {
        citations: [],
        columns: ["Model", "Parameters", "Year"],
        row_failures: [],
        rows: [
          { Model: "Transformer", Parameters: "65M", Year: 2017 },
          { Model: "BERT", Parameters: "110M", Year: 2018 },
        ],
        title: "Model comparison",
      },
      id: "76000000-0000-4000-8000-000000000004",
      kind: "data_table",
      scope_id: "73000000-0000-4000-8000-000000000001",
      scope_type: "project",
    },
    source: {
      scope_id: "73000000-0000-4000-8000-000000000001",
      scope_type: "project",
      title: "Thesis literature review",
    },
    title: "Model comparison",
  },
];

export const libraryConversations: Conversation[] = [
  {
    archived_at: null,
    capabilities: {
      archive: true,
      delete: true,
      detach: false,
      move: true,
      pin: true,
      rename: true,
      send: true,
      share: false,
    },
    id: "74000000-0000-4000-8000-000000000001",
    pinned_at: null,
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: null,
    scope_label: null,
    scope_type: "global",
    title: "Compare retrieval methods",
    updated_at: now,
  },
];

export const processingIngestion: LibraryPaperIngestion = {
  created_at: now,
  document_id: null,
  display_name: "agentic-systems.pdf",
  error_code: null,
  id: "75000000-0000-4000-8000-000000000001",
  project_id: null,
  source_kind: "upload",
  stage: "parsing",
  state: "processing",
};

export const failedIngestion: LibraryPaperIngestion = {
  ...processingIngestion,
  display_name: "encrypted-paper.pdf",
  error_code: "paper_source_pdf_unavailable",
  id: "75000000-0000-4000-8000-000000000002",
  stage: "queued",
  state: "failed",
};

export const processingIngestionEntry = {
  entry_type: "ingestion" as const,
  ingestion: processingIngestion,
};

export const failedIngestionEntry = {
  entry_type: "ingestion" as const,
  ingestion: failedIngestion,
};
