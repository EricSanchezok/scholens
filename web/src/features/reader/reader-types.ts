import type { components } from "@/lib/api/generated/schema";

export type ReaderContextPanel =
  "ask" | "annotations" | "translation" | "details";
export type ReaderNavigationMode = "thumbnails" | "outline";
export type ReaderDocumentView = "pdf" | "reflow";
export type ReaderDocument = components["schemas"]["DocumentResponse"];
export type ReaderAnnotation = components["schemas"]["ResearchItemResponse"];
export type ReaderAnnotationSummary =
  components["schemas"]["AnnotationThreadSummaryResponse"];
export type ReaderConversation =
  components["schemas"]["ConversationSummaryResponse"];
export type ReaderDocumentSource =
  components["schemas"]["DocumentAnswerSource"];
export type ReaderProject = components["schemas"]["ProjectResponse"];
export type ReaderAnnotationAudience = "personal" | "project";
export type ReaderAnnotationAudienceFilter = "all" | "personal" | "project";
export type ReaderAnnotationMode = "all" | "highlight" | "note" | "discussion";
export type ReaderAnnotationStatus = "open" | "resolved";
