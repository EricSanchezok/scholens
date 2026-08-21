import type { components } from "@/lib/api/generated/schema";

type PaperSelectionTurnContext =
  components["schemas"]["PaperSelectionTurnContext"];

export type ReaderSelection = PaperSelectionTurnContext & {
  /** UI-only page containing the browser focus end of a multi-page selection. */
  focus_page_number?: number;
};

export function readerSelectionFocusPage(selection: ReaderSelection) {
  return selection.focus_page_number ?? selection.page_number;
}

export function readerSelectionTurnContext(
  selection: ReaderSelection,
): PaperSelectionTurnContext {
  const context = { ...selection };
  delete context.focus_page_number;
  return context;
}
