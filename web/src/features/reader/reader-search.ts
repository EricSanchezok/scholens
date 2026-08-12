import type { PdfSearchResult } from "./pdf-document-adapter";

export type ReaderSearchMatch = {
  ordinal: number;
  pageNumber: number;
};

export function flattenReaderSearchResults(results: PdfSearchResult[]) {
  let ordinal = 0;
  return results.flatMap<ReaderSearchMatch>((result) =>
    Array.from({ length: result.count }, () => ({
      ordinal: (ordinal += 1),
      pageNumber: result.pageNumber,
    })),
  );
}

export function moveReaderSearchCursor(
  currentIndex: number,
  matchCount: number,
  direction: -1 | 1,
) {
  if (matchCount === 0) return -1;
  return (currentIndex + direction + matchCount) % matchCount;
}
