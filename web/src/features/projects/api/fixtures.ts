import type { components } from "@/lib/api/generated/schema";

type Project = components["schemas"]["ProjectResponse"];
type Paper = components["schemas"]["ProjectPaperSummaryResponse"];
type Output = components["schemas"]["LibraryOutputResponse"];
type Conversation = components["schemas"]["ConversationSummaryResponse"];
type LibraryPaper = components["schemas"]["LibraryPaperListPaperEntry"];
type ProjectMember = components["schemas"]["AvatarProjectCollaboratorResponse"];
type ProjectInvitation = components["schemas"]["ProjectInvitationResponse"];

const owner = {
  display_name: "Eric Sanchez",
  email: "eric@example.com",
  id: 7,
};
const fixtureAvatar = {
  expires_at: "2026-08-21T10:15:00Z",
  url: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' fill='%23272b35'/%3E%3Ccircle cx='32' cy='25' r='13' fill='%23d9b08c'/%3E%3Cpath d='M10 64c2-17 10-25 22-25s20 8 22 25' fill='%2386a8e7'/%3E%3C/svg%3E",
  version: "11111111-1111-1111-1111-111111111111",
};
const capabilities = {
  contribute_research: true,
  create_conversation: true,
  delete: true,
  edit_project: true,
  leave: false,
  manage_collaborators: true,
  manage_papers: true,
  read: true,
  transfer: true,
};

export const projectFixtures: Project[] = [
  {
    activity_at: "2026-08-13T09:42:00Z",
    capabilities,
    created_at: "2026-07-02T09:00:00Z",
    description: "Evidence-backed reasoning for a safer AI research workflow.",
    id: "20000000-0000-4000-8000-000000000001",
    membership: {
      kind: "owner",
      permissions: {
        edit_project: true,
        manage_collaborators: true,
        manage_papers: true,
      },
    },
    num_collaborators: 1,
    num_conversations: 7,
    num_outputs: 4,
    num_papers: 18,
    owner,
    title: "Truthward",
    updated_at: "2026-08-12T08:00:00Z",
  },
  {
    activity_at: "2026-08-10T05:20:00Z",
    capabilities: {
      ...capabilities,
      delete: false,
      leave: true,
      transfer: false,
    },
    created_at: "2026-07-14T09:00:00Z",
    description:
      "Compare retrieval quality across long-context evaluation suites.",
    id: "20000000-0000-4000-8000-000000000002",
    membership: {
      kind: "collaborator",
      permissions: {
        edit_project: true,
        manage_collaborators: false,
        manage_papers: true,
      },
    },
    num_collaborators: 5,
    num_conversations: 3,
    num_outputs: 6,
    num_papers: 12,
    owner: { display_name: "Mina Park", email: "mina@example.com", id: 8 },
    title: "Long-context retrieval",
    updated_at: "2026-08-10T05:20:00Z",
  },
];

export const projectMemberFixtures: ProjectMember[] = [
  {
    avatar: fixtureAvatar,
    display_name: owner.display_name,
    email: owner.email,
    is_owner: true,
    joined_at: null,
    permissions: {
      edit_project: true,
      manage_collaborators: true,
      manage_papers: true,
    },
    user_id: owner.id,
  },
  {
    display_name: "Mina Park",
    email: "mina@example.com",
    is_owner: false,
    joined_at: "2026-08-02T09:00:00Z",
    permissions: {
      edit_project: true,
      manage_collaborators: false,
      manage_papers: true,
    },
    user_id: 8,
  },
];

export const projectInvitationFixtures: ProjectInvitation[] = [
  {
    created_at: "2026-08-15T08:00:00Z",
    delivered_at: null,
    delivery_status: "pending",
    email: "pending@example.com",
    expires_at: "2026-08-22T08:00:00Z",
    id: "60000000-0000-4000-8000-000000000001",
    invited_by: owner.display_name,
    permissions: {
      edit_project: false,
      manage_collaborators: false,
      manage_papers: false,
    },
    project_id: projectFixtures[0]!.id,
    project_name: projectFixtures[0]!.title,
  },
  {
    created_at: "2026-08-13T08:00:00Z",
    delivered_at: "2026-08-13T08:01:14Z",
    delivery_status: "sent",
    email: "delivered@example.com",
    expires_at: "2026-08-20T08:00:00Z",
    id: "60000000-0000-4000-8000-000000000003",
    invited_by: owner.display_name,
    permissions: {
      edit_project: false,
      manage_collaborators: false,
      manage_papers: true,
    },
    project_id: projectFixtures[0]!.id,
    project_name: projectFixtures[0]!.title,
  },
  {
    created_at: "2026-08-14T08:00:00Z",
    delivered_at: null,
    delivery_status: "failed",
    email: "failed@example.com",
    expires_at: "2026-08-21T08:00:00Z",
    id: "60000000-0000-4000-8000-000000000002",
    invited_by: owner.display_name,
    permissions: {
      edit_project: true,
      manage_collaborators: false,
      manage_papers: true,
    },
    project_id: projectFixtures[0]!.id,
    project_name: projectFixtures[0]!.title,
  },
];

export const projectPaperFixtures: Paper[] = [
  {
    abstract:
      "A transformer architecture based solely on attention mechanisms.",
    added_at: "2026-08-12T08:00:00Z",
    authors: ["Ashish Vaswani", "Noam Shazeer"],
    document_id: "10000000-0000-4000-8000-000000000001",
    doi: "10.5555/3295222.3295349",
    file_url: null,
    in_library: true,
    institutions: ["Google Brain"],
    journal: null,
    publish_date: "2017-06-12T00:00:00Z",
    publisher: "NeurIPS",
    status: "reading",
    title: "Attention Is All You Need",
  },
  {
    abstract: "Retrieval-augmented generation for knowledge-intensive tasks.",
    added_at: "2026-08-10T08:00:00Z",
    authors: ["Patrick Lewis", "Ethan Perez"],
    document_id: "10000000-0000-4000-8000-000000000002",
    doi: null,
    file_url: null,
    in_library: true,
    institutions: null,
    journal: null,
    publish_date: "2020-05-22T00:00:00Z",
    publisher: null,
    status: "reading",
    title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
  },
];

export const projectLibraryPaperFixtures: LibraryPaper[] =
  projectPaperFixtures.map((paper, index) => ({
    created_at: paper.added_at,
    document: {
      abstract: paper.abstract,
      authors: paper.authors,
      created_at: paper.added_at,
      document_id: paper.document_id,
      doi: paper.doi,
      institutions: paper.institutions,
      journal: paper.journal,
      keywords: null,
      mime_type: "application/pdf",
      original_filename: `${paper.title ?? "paper"}.pdf`,
      parser_quality: "high",
      parser_warning_code: null,
      processing_status: "completed",
      publish_date: paper.publish_date,
      publisher: paper.publisher,
      size_bytes: 1_280_000,
      starter_questions: null,
      summary: null,
      summary_citations: null,
      title: paper.title,
      updated_at: paper.added_at,
    },
    entry_type: "paper",
    is_public: false,
    last_accessed_at: paper.added_at,
    library_entry_id: `50000000-0000-4000-8000-00000000000${index + 1}`,
    metadata_overrides: {},
    preview_url: null,
    status: "reading",
    tags: [],
    updated_at: paper.added_at,
    user_id: 7,
  }));

export const projectOutputFixtures: Output[] = [
  {
    item: {
      audio_overview: null,
      annotation_thread: null,
      audience: { kind: "project", project_id: projectFixtures[0]!.id },
      capabilities: { delete: true, edit: true },
      citation: {
        snapshot: {
          confidence: 0.98,
          data: {
            document_id: "10000000-0000-4000-8000-000000000001",
            title: "Attention Is All You Need",
          },
          document_id: "10000000-0000-4000-8000-000000000001",
          kind: "citation",
          method: "deterministic",
          missing_fields: [],
          preferred_style: "apa",
          style_display: "APA",
        },
      },
      created_at: "2026-08-11T08:00:00Z",
      created_by: { display_name: "Eric Sanchez", id: 7 },
      data_table: null,
      id: "30000000-0000-4000-8000-000000000001",
      kind: "citation",
      target_document_id: "10000000-0000-4000-8000-000000000001",
      updated_at: "2026-08-12T09:10:00Z",
    },
    source: {
      audience_id: projectFixtures[0]!.id,
      audience_type: "project",
      title: projectFixtures[0]!.title,
    },
    title:
      "What matters is designing agents that can thrive within an interconnected ecosystem of peers, specialists, and collaborators they have never encountered",
  },
];

export const projectConversationFixtures: Conversation[] = [
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
    id: "40000000-0000-4000-8000-000000000001",
    pinned_at: "2026-08-13T09:45:00Z",
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: projectFixtures[0]!.id,
    scope_label: projectFixtures[0]!.title,
    scope_type: "project",
    title: "Compare retrieval baselines",
    updated_at: "2026-08-13T09:42:00Z",
  },
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
    id: "40000000-0000-4000-8000-000000000002",
    pinned_at: null,
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: projectFixtures[0]!.id,
    scope_label: projectFixtures[0]!.title,
    scope_type: "project",
    title: "Trace the strongest counter-evidence",
    updated_at: "2026-08-12T09:42:00Z",
  },
];
