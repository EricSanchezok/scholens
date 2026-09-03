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

/**
 * Returns the stable identity of a selection for comparing async actions with
 * the selection that is currently shown in the Reader.
 *
 * `focus_page_number` is intentionally excluded because it is a UI-only hint
 * and does not change the persisted selection anchor or quote.
 */
export function readerSelectionKey(selection: ReaderSelection | undefined) {
  if (!selection) return undefined;
  return JSON.stringify([
    selection.document_id,
    selection.page_number,
    selection.selected_text,
    selection.anchor,
  ]);
}

export function readerSelectionTurnContext(
  selection: ReaderSelection,
): PaperSelectionTurnContext {
  const context = { ...selection };
  delete context.focus_page_number;
  return context;
}
