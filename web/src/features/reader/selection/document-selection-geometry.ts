import type { NormalizedSelectionRect } from "./rect-normalization";

export const MAX_DOCUMENT_SELECTION_RECTS = 200;

export type DocumentSelectionSegment = {
  pageNumber: number;
  rects: NormalizedSelectionRect[];
};

function evenlySpacedItems<T>(items: T[], count: number) {
  if (count >= items.length) return items;
  if (count === 1) return [items[Math.floor((items.length - 1) / 2)]!];
  return Array.from(
    { length: count },
    (_, index) =>
      items[Math.round((index * (items.length - 1)) / (count - 1))]!,
  );
}

export function limitDocumentSelectionSegments(
  segments: DocumentSelectionSegment[],
  focusPageNumber?: number,
) {
  if (segments.length === 0) return segments;

  let boundedSegments = segments;
  if (segments.length > MAX_DOCUMENT_SELECTION_RECTS) {
    const indexes = evenlySpacedItems(
      segments.map((_, index) => index),
      MAX_DOCUMENT_SELECTION_RECTS,
    );
    const focusIndex = segments.findIndex(
      (segment) => segment.pageNumber === focusPageNumber,
    );
    if (focusIndex >= 0 && !indexes.includes(focusIndex)) {
      const replaceAt = indexes
        .map((index, position) => ({
          distance: Math.abs(index - focusIndex),
          position,
        }))
        .filter(({ position }) => position > 0 && position < indexes.length - 1)
        .sort((left, right) => left.distance - right.distance)[0]?.position;
      if (replaceAt !== undefined) indexes[replaceAt] = focusIndex;
      indexes.sort((left, right) => left - right);
    }
    boundedSegments = indexes.map((index) => segments[index]!);
  }

  const totalRects = boundedSegments.reduce(
    (total, segment) => total + segment.rects.length,
    0,
  );
  if (totalRects <= MAX_DOCUMENT_SELECTION_RECTS) return boundedSegments;

  const quotas = boundedSegments.map(() => 1);
  let remaining = MAX_DOCUMENT_SELECTION_RECTS - boundedSegments.length;
  while (remaining > 0) {
    let allocated = false;
    for (let index = 0; index < boundedSegments.length; index += 1) {
      if (remaining === 0) break;
      if (quotas[index]! >= boundedSegments[index]!.rects.length) continue;
      quotas[index]! += 1;
      remaining -= 1;
      allocated = true;
    }
    if (!allocated) break;
  }

  return boundedSegments.map((segment, index) => ({
    ...segment,
    rects: evenlySpacedItems(segment.rects, quotas[index]!),
  }));
}
