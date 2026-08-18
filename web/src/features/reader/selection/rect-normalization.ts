/**
 * Rectangle normalization for `pdf_text` anchors.
 *
 * Converts client-space selection rectangles into the normalized 0..1 page
 * coordinate space used by the `pdf_text` anchor contract, rejecting
 * page-sized/out-of-page artifacts and coalescing overlapping fragments on
 * the same visual line so translucent overlay color never accumulates.
 */

export type ClientRect = {
  height: number;
  left: number;
  top: number;
  width: number;
};

export type NormalizedSelectionRect = {
  height: number;
  width: number;
  x: number;
  y: number;
};

export function coalesceSelectionRects(rects: ClientRect[]): ClientRect[] {
  const merged: ClientRect[] = [];

  for (const rect of rects.sort(
    (left, right) => left.top - right.top || left.left - right.left,
  )) {
    const match = merged.find((candidate) => {
      const verticalOverlap = Math.max(
        0,
        Math.min(candidate.top + candidate.height, rect.top + rect.height) -
          Math.max(candidate.top, rect.top),
      );
      const overlapRatio =
        verticalOverlap / Math.min(candidate.height, rect.height);
      const horizontalGap = Math.max(
        0,
        rect.left - (candidate.left + candidate.width),
        candidate.left - (rect.left + rect.width),
      );
      return (
        overlapRatio >= 0.55 &&
        horizontalGap <=
          Math.max(2, Math.min(candidate.height, rect.height) / 2)
      );
    });

    if (!match) {
      merged.push({ ...rect });
      continue;
    }

    const right = Math.max(match.left + match.width, rect.left + rect.width);
    const bottom = Math.max(match.top + match.height, rect.top + rect.height);
    match.left = Math.min(match.left, rect.left);
    match.top = Math.min(match.top, rect.top);
    match.width = right - match.left;
    match.height = bottom - match.top;
  }

  return merged;
}

export function normalizeReaderSelectionRects(
  pageRect: ClientRect,
  clientRects: ClientRect[],
): NormalizedSelectionRect[] {
  if (pageRect.width <= 0 || pageRect.height <= 0) return [];
  const pageRight = pageRect.left + pageRect.width;
  const pageBottom = pageRect.top + pageRect.height;
  const containmentTolerance = 1;
  const clippedRects = clientRects
    .filter((rect) => {
      const rectRight = rect.left + rect.width;
      const rectBottom = rect.top + rect.height;
      return (
        rect.width > 0 &&
        rect.height > 0 &&
        rect.width < pageRect.width &&
        rect.height < pageRect.height &&
        rect.left >= pageRect.left - containmentTolerance &&
        rect.top >= pageRect.top - containmentTolerance &&
        rectRight <= pageRight + containmentTolerance &&
        rectBottom <= pageBottom + containmentTolerance
      );
    })
    .map((rect) => ({
      left: Math.max(pageRect.left, Math.min(pageRight, rect.left)),
      top: Math.max(pageRect.top, Math.min(pageBottom, rect.top)),
      width:
        Math.max(pageRect.left, Math.min(pageRight, rect.left + rect.width)) -
        Math.max(pageRect.left, Math.min(pageRight, rect.left)),
      height:
        Math.max(pageRect.top, Math.min(pageBottom, rect.top + rect.height)) -
        Math.max(pageRect.top, Math.min(pageBottom, rect.top)),
    }))
    .filter((rect) => rect.width > 0 && rect.height > 0);

  return coalesceSelectionRects(clippedRects).map((rect) => ({
    x: (rect.left - pageRect.left) / pageRect.width,
    y: (rect.top - pageRect.top) / pageRect.height,
    width: rect.width / pageRect.width,
    height: rect.height / pageRect.height,
  }));
}
