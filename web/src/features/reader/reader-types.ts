import type { components } from "@/lib/api/generated/schema";

export type ReaderContextPanel = "ask" | "annotations" | "details";
export type ReaderNavigationMode = "thumbnails" | "outline";
export type ReaderDocument = components["schemas"]["DocumentResponse"];
export type ReaderAnnotation = components["schemas"]["ResearchItemResponse"];
export type ReaderConversation =
  components["schemas"]["ConversationSummaryResponse"];
export type ReaderDocumentSource =
  components["schemas"]["DocumentAnswerSource"];
export type ReaderProject = components["schemas"]["ProjectResponse"];
export type ReaderAnnotationAudience = "personal" | "project";
export type ReaderAnnotationAudienceFilter = "all" | "mine" | "project";
export type ReaderAnnotationStatus = "open" | "resolved";
