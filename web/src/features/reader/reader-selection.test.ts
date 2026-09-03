import { describe, expect, it } from "vitest";

import { readerSelectionKey, type ReaderSelection } from "./reader-selection";

const selection: ReaderSelection = {
  anchor: {
    kind: "pdf_text",
    page_number: 2,
    rects: [{ height: 0.02, width: 0.2, x: 0.1, y: 0.3 }],
  },
  document_id: "document-1",
  focus_page_number: 2,
  kind: "paper_selection",
  page_number: 2,
  selected_text: "A selected passage",
};

describe("readerSelectionKey", () => {
  it("ignores the UI-only focus page when identifying a selection", () => {
    expect(readerSelectionKey({ ...selection, focus_page_number: 3 })).toBe(
      readerSelectionKey(selection),
    );
  });

  it("changes when the persisted selection changes", () => {
    expect(
      readerSelectionKey({ ...selection, selected_text: "Another passage" }),
    ).not.toBe(readerSelectionKey(selection));
  });

  it("returns no key for an empty selection", () => {
    expect(readerSelectionKey(undefined)).toBeUndefined();
  });
});
