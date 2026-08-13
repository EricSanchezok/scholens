import type { components } from "@/lib/api/generated/schema";

import type { ReaderContextPanel, ReaderDocumentSource } from "./reader-types";

type ConversationDetail = components["schemas"]["ConversationDetailResponse"];

export function parsePositiveInteger(value: string | null, fallback = 1) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : fallback;
}

export function readReaderPanel(
  value: string | null,
): ReaderContextPanel | undefined {
  return value === "ask" || value === "annotations" || value === "details"
    ? value
    : undefined;
}

export function readSourcePage(locator: ReaderDocumentSource["locator"]) {
  if (!locator) return undefined;
  const value = locator.page_number ?? locator.page;
  const page = typeof value === "number" ? value : Number(value);
  return Number.isInteger(page) && page > 0 ? page : undefined;
}

export function conversationBelongsToReaderContext({
  conversation,
  documentId,
  projectId,
}: {
  conversation: ConversationDetail;
  documentId: string;
  projectId?: string;
}) {
  if (!projectId) {
    return (
      conversation.scope_type === "paper" &&
      conversation.scope_id === documentId
    );
  }

  return (
    conversation.scope_type === "project" &&
    conversation.scope_id === projectId &&
    conversation.paper_context.kind === "selection" &&
    (conversation.paper_context.document_ids ?? []).includes(documentId)
  );
}
