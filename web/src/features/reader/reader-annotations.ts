import type { ReaderAnnotationSummary } from "./reader-types";

function anchorOrder(annotation: ReaderAnnotationSummary) {
  const position = annotation.position;
  if (!position) return [Number.MAX_SAFE_INTEGER, 1, 1] as const;
  if (position.kind === "parsed_text") {
    return [
      position.page_number ?? Number.MAX_SAFE_INTEGER,
      position.start_offset,
      position.end_offset,
    ] as const;
  }
  const firstRect = [...position.rects].sort(
    (left, right) => left.y - right.y || left.x - right.x,
  )[0];
  return [position.page_number, firstRect?.y ?? 1, firstRect?.x ?? 1] as const;
}

export function compareReaderAnnotationsBySource(
  left: ReaderAnnotationSummary,
  right: ReaderAnnotationSummary,
) {
  const leftOrder = anchorOrder(left);
  const rightOrder = anchorOrder(right);
  for (let index = 0; index < leftOrder.length; index += 1) {
    const difference = leftOrder[index]! - rightOrder[index]!;
    if (difference !== 0) return difference;
  }
  const createdDifference = left.created_at.localeCompare(right.created_at);
  return createdDifference || left.id.localeCompare(right.id);
}
