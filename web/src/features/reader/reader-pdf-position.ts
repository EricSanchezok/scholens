import type { components } from "@/lib/api/generated/schema";

type PdfTextPosition = components["schemas"]["PdfTextPosition"];
type PdfTextPageSegment = components["schemas"]["PdfTextPageSegment"];

export function readerPdfPositionSegments(
  position: PdfTextPosition,
): PdfTextPageSegment[] {
  return position.segments?.length
    ? position.segments
    : [{ page_number: position.page_number, rects: position.rects }];
}

export function readerPdfRectsForPage(
  position: PdfTextPosition,
  pageNumber: number,
) {
  return readerPdfPositionSegments(position).find(
    (segment) => segment.page_number === pageNumber,
  )?.rects;
}

export function readerPdfPageRange(position: PdfTextPosition) {
  const segments = readerPdfPositionSegments(position);
  return {
    end: segments.at(-1)!.page_number,
    start: segments[0]!.page_number,
  };
}
