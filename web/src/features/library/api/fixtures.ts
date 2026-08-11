import type { components } from "@/lib/api/generated/schema";

type Conversation = components["schemas"]["ConversationSummaryResponse"];
type Job = components["schemas"]["JobResponse"];
type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];
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

export const libraryProjects: Project[] = [
  {
    capabilities: {
      contribute_research: true,
      create_conversation: true,
      delete: true,
      edit_project: true,
      leave: false,
      manage_collaborators: true,
      manage_papers: true,
      read: true,
      transfer: true,
    },
    created_at: now,
    description: null,
    id: "73000000-0000-4000-8000-000000000001",
    membership: {
      kind: "owner",
      permissions: {
        edit_project: true,
        manage_collaborators: true,
        manage_papers: true,
      },
    },
    num_audio_overviews: 0,
    num_collaborators: 2,
    num_conversations: 4,
    num_data_tables: 1,
    num_papers: 12,
    owner: { display_name: "Eric", email: "eric@scholens.ai", id: 7 },
    title: "Thesis literature review",
    updated_at: now,
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

export const processingJob: Job = {
  completed_at: null,
  created_at: now,
  document_id: null,
  error_code: null,
  id: "75000000-0000-4000-8000-000000000001",
  operation: "pdf_process",
  progress_message: "Parsing PDF",
  project_id: null,
  result: null,
  started_at: now,
  status: "running",
};

export const failedJob: Job = {
  ...processingJob,
  error_code: "paper_source_pdf_unavailable",
  id: "75000000-0000-4000-8000-000000000002",
  progress_message: null,
  started_at: null,
  status: "failed",
};
