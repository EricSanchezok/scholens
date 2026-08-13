import { describe, expect, it } from "vitest";

import {
  conversationBelongsToReaderContext,
  parsePositiveInteger,
  readReaderPanel,
  readSourcePage,
} from "./reader-routing";

const conversation = {
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
  id: "conversation-1",
  paper_context: {
    kind: "selection" as const,
    document_ids: ["document-1"],
    project_ids: ["project-1"],
  },
  pinned_at: null,
  read_only: false,
  read_only_reason: null,
  scope_access: "active" as const,
  scope_id: "document-1",
  scope_label: "Paper",
  scope_type: "paper" as const,
  title: "Conversation",
  tool_permissions: [],
  updated_at: "2026-08-14T00:00:00Z",
};

describe("reader URL state", () => {
  it("accepts only positive integer page numbers", () => {
    expect(parsePositiveInteger("12")).toBe(12);
    expect(parsePositiveInteger("0", 3)).toBe(3);
    expect(parsePositiveInteger("1.5", 3)).toBe(3);
    expect(parsePositiveInteger(null, 3)).toBe(3);
  });

  it("rejects unknown panel values", () => {
    expect(readReaderPanel("annotations")).toBe("annotations");
    expect(readReaderPanel("search")).toBeUndefined();
    expect(readReaderPanel("outline")).toBeUndefined();
    expect(readReaderPanel("translation")).toBe("translation");
    expect(readReaderPanel(null)).toBeUndefined();
  });

  it("reads document source pages without trusting invalid locators", () => {
    expect(readSourcePage({ page_number: 8 })).toBe(8);
    expect(readSourcePage({ page: "4" })).toBe(4);
    expect(readSourcePage({ page_number: -1 })).toBeUndefined();
    expect(readSourcePage({ page: "chapter-two" })).toBeUndefined();
  });

  it("validates an active conversation against the authoritative Reader scope", () => {
    expect(
      conversationBelongsToReaderContext({
        conversation,
        documentId: "document-1",
      }),
    ).toBe(true);
    expect(
      conversationBelongsToReaderContext({
        conversation,
        documentId: "document-2",
      }),
    ).toBe(false);

    const projectConversation = {
      ...conversation,
      scope_id: "project-1",
      scope_type: "project" as const,
    };
    expect(
      conversationBelongsToReaderContext({
        conversation: projectConversation,
        documentId: "document-1",
        projectId: "project-1",
      }),
    ).toBe(true);
    expect(
      conversationBelongsToReaderContext({
        conversation: projectConversation,
        documentId: "document-2",
        projectId: "project-1",
      }),
    ).toBe(false);
  });
});
