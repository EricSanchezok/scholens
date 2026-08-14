import { describe, expect, it } from "vitest";

import type { ReaderAnnotationSummary } from "./reader-types";
import { compareReaderAnnotationsBySource } from "./reader-annotations";

function summary(
  id: string,
  page: number,
  x: number,
  y: number,
  lastActivity: string,
) {
  return {
    id,
    created_at: "2026-08-14T00:00:00Z",
    last_activity_at: lastActivity,
    position: {
      kind: "pdf_text",
      page_number: page,
      rects: [{ x, y, width: 0.2, height: 0.03 }],
    },
  } as ReaderAnnotationSummary;
}

describe("compareReaderAnnotationsBySource", () => {
  it("keeps annotations in document order instead of recent activity order", () => {
    const laterReplyNearTop = summary(
      "top",
      1,
      0.1,
      0.2,
      "2026-08-14T04:00:00Z",
    );
    const olderReplyNearBottom = summary(
      "bottom",
      1,
      0.1,
      0.8,
      "2026-08-14T01:00:00Z",
    );
    const nextPage = summary("next-page", 2, 0.1, 0.1, "2026-08-14T05:00:00Z");

    expect(
      [nextPage, olderReplyNearBottom, laterReplyNearTop]
        .sort(compareReaderAnnotationsBySource)
        .map(({ id }) => id),
    ).toEqual(["top", "bottom", "next-page"]);
  });
});
