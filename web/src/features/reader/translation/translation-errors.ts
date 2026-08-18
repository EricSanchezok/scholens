export type TranslationErrorMessageKey =
  | "errors.quota"
  | "errors.busy"
  | "errors.inProgress"
  | "errors.provider"
  | "errors.access"
  | "errors.edgeBlocked"
  | "errors.generic";

export function translationErrorMessageKey(
  code: string | undefined,
): TranslationErrorMessageKey {
  switch (code) {
    case "token_quota_exceeded":
      return "errors.quota";
    case "translation_rate_limited":
    case "translation_concurrency_limited":
      return "errors.busy";
    case "translation_in_progress":
      return "errors.inProgress";
    case "translation_provider_unavailable":
      return "errors.provider";
    case "paper_not_found":
      return "errors.access";
    case "edge_blocked":
      return "errors.edgeBlocked";
    default:
      return "errors.generic";
  }
}
