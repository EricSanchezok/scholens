import type { components } from "@/lib/api/generated/schema";

export type ReaderPanel =
  "ask" | "annotations" | "details" | "outline" | "search";
export type ReaderDocument = components["schemas"]["DocumentResponse"];
export type ReaderAnnotation = components["schemas"]["ResearchItemResponse"];
export type ReaderConversation =
  components["schemas"]["ConversationSummaryResponse"];
export type ReaderDocumentSource =
  components["schemas"]["DocumentAnswerSource"];
