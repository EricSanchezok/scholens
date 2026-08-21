import { describe, expect, it } from "vitest";

import {
  limitDocumentSelectionSegments,
  MAX_DOCUMENT_SELECTION_RECTS,
} from "./document-selection-geometry";

describe("limitDocumentSelectionSegments", () => {
  it("keeps bounded geometry unchanged and deterministically caps oversized anchors", () => {
    const rects = Array.from({ length: 201 }, (_, index) => ({
      height: 0.01,
      width: 0.01,
      x: index / 1_000,
      y: index / 1_000,
    }));
    const atLimit = [
      { pageNumber: 1, rects: rects.slice(0, 100) },
      { pageNumber: 2, rects: rects.slice(101) },
    ];
    expect(limitDocumentSelectionSegments(atLimit)).toBe(atLimit);

    const oversized = [
      { pageNumber: 1, rects: rects.slice(0, 101) },
      { pageNumber: 2, rects: rects.slice(101) },
    ];
    const first = limitDocumentSelectionSegments(oversized);
    const second = limitDocumentSelectionSegments(oversized);

    expect(first).toEqual(second);
    expect(first.map((segment) => segment.rects.length)).toEqual([100, 100]);
    expect(first.flatMap((segment) => segment.rects)).toHaveLength(
      MAX_DOCUMENT_SELECTION_RECTS,
    );
    expect(first[0]!.rects.at(0)).toBe(rects[0]);
    expect(first[0]!.rects.at(-1)).toBe(rects[100]);
    expect(first[1]!.rects.at(0)).toBe(rects[101]);
    expect(first[1]!.rects.at(-1)).toBe(rects[200]);
  });

  it("keeps the endpoints and focus page when a selection exceeds the page budget", () => {
    const rect = { height: 0.01, width: 0.01, x: 0.1, y: 0.1 };
    const segments = Array.from(
      { length: MAX_DOCUMENT_SELECTION_RECTS + 3 },
      (_, index) => ({ pageNumber: index + 1, rects: [rect] }),
    );
    const withoutFocus = limitDocumentSelectionSegments(segments);
    const omitted = segments.find(
      (segment) =>
        !withoutFocus.some(
          (candidate) => candidate.pageNumber === segment.pageNumber,
        ),
    )!;

    const bounded = limitDocumentSelectionSegments(
      segments,
      omitted.pageNumber,
    );

    expect(bounded).toHaveLength(MAX_DOCUMENT_SELECTION_RECTS);
    expect(bounded.at(0)?.pageNumber).toBe(1);
    expect(bounded.at(-1)?.pageNumber).toBe(segments.length);
    expect(
      bounded.some((segment) => segment.pageNumber === omitted.pageNumber),
    ).toBe(true);
  });
});
