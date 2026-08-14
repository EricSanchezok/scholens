import { describe, expect, it } from "vitest";

import type { DocumentReflowBlock } from "./api";
import {
  isTranslatableReflowBlock,
  reflowMarkdownPlainText,
  sanitizeAcademicMarkdown,
} from "./reader-reflow-view";

function block(kind: DocumentReflowBlock["kind"]): DocumentReflowBlock {
  return {
    asset_id: null,
    group_id: null,
    heading_level: null,
    id: kind,
    index: 0,
    kind,
    page_number: 1,
    presentation_status: "verbatim",
    render_markdown: "source",
    source_markdown: "source",
    source_rect: null,
  };
}

describe("academic reflow rendering", () => {
  it("converts supported inline academic HTML without exposing raw tags", () => {
    const value = sanitizeAcademicMarkdown(
      "Author<sup>1,2</sup><!-- hidden --><br>H<sub>2</sub>O <unknown>visible</unknown> �",
    );

    expect(value).toBe("Author$^{1,2}$  \nH$_{2}$O visible ");
    expect(value).not.toContain("<sup>");
    expect(value).not.toContain("hidden");
    expect(value).not.toContain("�");
  });

  it("derives stable plain-text outline labels", () => {
    expect(reflowMarkdownPlainText("## **1 Method** $x^2$")).toBe(
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
});
