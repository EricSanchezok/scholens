import { describe, expect, it } from "vitest";

import { academicMarkdownToPlainText } from "@/lib/content/academic-text";
import type { DocumentReflowBlock } from "./api";
import {
  isTranslatableReflowBlock,
  primaryReflowSource,
} from "./reader-reflow-view";

function block(kind: DocumentReflowBlock["kind"]): DocumentReflowBlock {
  return {
    asset_id: null,
    group_id: null,
    heading_level: null,
    id: kind,
    index: 0,
    kind,
    presentation_status: "verbatim",
    render_markdown: "source",
    source_spans: [
      {
        page_number: 1,
        source_rect: { height: 0.1, width: 0.7, x: 0.15, y: 0.2 },
        source_text: "source",
      },
    ],
  };
}

describe("academic reflow rendering", () => {
  it("derives stable plain-text outline labels", () => {
    expect(academicMarkdownToPlainText("## **1 Method** $x^2$")).toBe(
      "1 Method x^2",
    );
  });

  it("translates semantic prose but protects identities and evidence syntax", () => {
    expect(isTranslatableReflowBlock(block("paragraph"), false)).toBe(true);
    expect(isTranslatableReflowBlock(block("authors"), false)).toBe(false);
    expect(isTranslatableReflowBlock(block("equation"), false)).toBe(false);
    expect(isTranslatableReflowBlock(block("references"), false)).toBe(false);
    expect(isTranslatableReflowBlock(block("references"), true)).toBe(true);
  });

  it("uses the first evidence span for PDF navigation", () => {
    expect(primaryReflowSource(block("paragraph"))?.page_number).toBe(1);
  });
});
