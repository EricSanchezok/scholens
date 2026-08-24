import { describe, expect, it } from "vitest";

import type { PaperSearchResult } from "./api";
import {
  PAPER_SEARCH_EXCERPT_LIMIT,
  paperSearchExcerpt,
  toPaperSearchCollectionItem,
} from "./paper-search-display";

const paper: PaperSearchResult = {
  abstract: "Abstract fallback",
  authors: ["Ada Lovelace"],
  created_at: "2026-08-20T08:00:00Z",
  document_id: "00000000-0000-4000-8000-000000000001",
  last_accessed_at: "2026-08-20T08:00:00Z",
  preview_url: null,
  publish_date: "2026-08-20T08:00:00Z",
  snippets: [],
  status: "completed",
  summary: "Summary fallback",
  title: "A paper",
};

const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });

describe("paper search display adapter", () => {
  it("prefers a cleaned passage over summary and abstract fallbacks", () => {
    expect(
      paperSearchExcerpt({
        ...paper,
        snippets: [
          {
            text: "## **Matched passage**<script>hidden()</script>\u0000<br>with [evidence](https://example.test)",
          },
        ],
      }),
    ).toBe("Matched passage with evidence");
  });

  it("falls through empty passages to summary, then abstract", () => {
    expect(
      paperSearchExcerpt({
        ...paper,
        snippets: [{ text: "<!-- no visible content -->" }],
      }),
    ).toBe("Summary fallback");
    expect(
      paperSearchExcerpt({
        ...paper,
        snippets: [],
        summary: null,
      }),
    ).toBe("Abstract fallback");
  });

  it("returns to a nearby word boundary for natural long text", () => {
    const natural = Array.from(
      { length: 100 },
      (_, index) => `research-term-${index}`,
    ).join(" ");
    const excerpt = paperSearchExcerpt({
      abstract: null,
      snippets: [{ text: natural }],
      summary: null,
    });
    const expectedBoundary = natural.lastIndexOf(
      " ",
      PAPER_SEARCH_EXCERPT_LIMIT - 2,
    );

    expect(excerpt).toBe(`${natural.slice(0, expectedBoundary)}…`);
  });

  it("hard-limits hostile unbroken Unicode without splitting graphemes", () => {
    const hostile = `${"界".repeat(600)}${"👩🏽‍💻".repeat(120)}`;
    const excerpt = paperSearchExcerpt({
      abstract: null,
      snippets: [{ text: hostile }],
      summary: null,
    });

    expect(excerpt).toBeDefined();
    expect(Array.from(segmenter.segment(excerpt ?? ""))).toHaveLength(
      PAPER_SEARCH_EXCERPT_LIMIT,
    );
    expect(excerpt?.endsWith("…")).toBe(true);
    expect(excerpt).not.toContain("�");
  });

  it("maps the normalized excerpt into the collection row exactly once", () => {
    const item = toPaperSearchCollectionItem(
      {
        ...paper,
        snippets: [{ text: "**Grounded** <em>result</em>" }],
      },
      {
        formatDate: (date) => date.toISOString().slice(0, 10),
        untitled: "Untitled",
      },
    );

    expect(item.snippet).toBe("Grounded result");
    expect(item.addedAt).toBe("2026-08-20");
  });
});
