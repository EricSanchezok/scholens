/**
 * Selection commit normalization.
 *
 * Turns a browser Range (treated as a hint) plus the page geometry index into
 * the single authoritative selection used by overlay, toolbar, translation,
 * Ask, annotations, and copy. The output is a page-order offset span together
 * with its synthesized text and client-space rectangles, so text and geometry
 * can never drift apart.
 */

import type {
  GeometryItem,
  GeometryPoint,
  GeometryRect,
  PageTextGeometryIndex,
} from "./page-text-geometry";
import { mapDomBoundaryToOffset } from "./page-text-geometry";

export type NormalizedSelection = {
  /** Page-order inclusive start offset. */
  start: number;
  /** Page-order exclusive end offset. */
  end: number;
  /** Trimmed, whitespace-collapsed selected text. */
  text: string;
  /** Client-space rectangles for the selected offsets. */
  rects: GeometryRect[];
};

/** Vertical dead-zone threshold: larger gaps between lines/paragraphs. */
export const DEAD_ZONE_LINE_FACTOR = 1.25;
export const DEAD_ZONE_MIN_PX = 8;

/** Overshoot guard: reject a commit that is wildly larger than the previous. */
export const OVERSHOOT_LENGTH_FACTOR = 3;
export const OVERSHOOT_ABSOLUTE_PADDING = 80;

/** Normalize text for integrity comparison (NFKC, whitespace collapse). */
export function normalizeForComparison(text: string) {
  return text.normalize("NFKC").replace(/\s+/g, " ").replace(/-\s/g, "").trim();
}

/**
 * Vertical gap between two items in reading order (0 when overlapping).
 * Uses top-of-next minus bottom-of-previous so adjacent lines read as
 * contiguous.
 */
export function verticalGapBetween(previous: GeometryItem, next: GeometryItem) {
  const bottom = previous.rect.top + previous.rect.height;
  const top = next.rect.top;
  return Math.max(0, top - bottom);
}

/**
 * Column strip filter: keep only items whose horizontal center lies inside
 * the anchor-head horizontal envelope (inflated by half an average item
 * width) so DOM-order text from a neighboring column is never merged in.
 */
export function columnStripItems(
  items: GeometryItem[],
  anchorCenterX: number,
  headCenterX: number,
) {
  const minX = Math.min(anchorCenterX, headCenterX);
  const maxX = Math.max(anchorCenterX, headCenterX);
  const averageWidth =
    items.reduce((sum, item) => sum + item.rect.width, 0) /
    Math.max(1, items.length);
  const tolerance = Math.max(averageWidth / 2, 4);
  return items.filter((item) => {
    const center = item.centerX;
    return center >= minX - tolerance && center <= maxX + tolerance;
  });
}

/**
 * Dead-zone clamp: collapse a range whose head jumped across a large
 * vertical gap without passing through any selectable text. Returns the
 * clamped end offset (the end of the last item above the pointer).
 */
export function clampDeadZoneEnd(
  index: PageTextGeometryIndex,
  start: number,
  end: number,
  pointerY: number,
) {
  const items = index.items.filter(
    (item) => item.end > start && item.start < end,
  );
  if (items.length === 0) return end;

  // Pointer inside a text item: no dead zone.
  const inside = items.findIndex(
    (item) =>
      item.rect.top <= pointerY && pointerY <= item.rect.top + item.rect.height,
  );
  if (inside >= 0) return end;

  // Last item whose bottom sits above (or at) the pointer.
  let upperIndex = -1;
  for (let i = 0; i < items.length; i += 1) {
    if (items[i]!.rect.top + items[i]!.rect.height <= pointerY) upperIndex = i;
  }
  if (upperIndex < 0 || upperIndex === items.length - 1) return end;

  const upper = items[upperIndex]!;
  const lower = items[upperIndex + 1]!;
  const gap = lower.rect.top - (upper.rect.top + upper.rect.height);
  const lineHeight = upper.rect.height || DEAD_ZONE_MIN_PX;
  const threshold = Math.max(
    lineHeight * DEAD_ZONE_LINE_FACTOR,
    DEAD_ZONE_MIN_PX,
  );
  if (gap <= threshold) return end;
  // Pointer landed in a dead zone: stop at the last item above it.
  return upper.end;
}

/**
 * Commit a selection from a browser Range over one page's geometry.
 *
 * @returns the normalized selection, or undefined when the range is not on
 * this page / contains no selectable text / is rejected by the overshoot guard.
 */
export function normalizePdfSelection({
  index,
  range,
  previous,
  pointerPoint,
}: {
  index: PageTextGeometryIndex;
  range: Range;
  previous?: NormalizedSelection;
  pointerPoint?: GeometryPoint;
}): NormalizedSelection | undefined {
  const textLayer = index.textLayer;
  const ancestor =
    range.commonAncestorContainer.nodeType === Node.TEXT_NODE
      ? range.commonAncestorContainer.parentElement
      : (range.commonAncestorContainer as Element | null);
  if (!ancestor || !textLayer.contains(ancestor)) return undefined;

  let start = mapDomBoundaryToOffset(
    index,
    range.startContainer,
    range.startOffset,
    true,
  );
  let end = mapDomBoundaryToOffset(
    index,
    range.endContainer,
    range.endOffset,
    false,
  );
  if (end < start) [start, end] = [end, start];

  const items = index.items.filter(
    (item) => item.end > start && item.start < end,
  );
  if (items.length === 0) return undefined;

  const anchorItem = items[0]!;
  const headItem = items[items.length - 1]!;

  // Column strip: only include items in the anchor-head horizontal envelope
  // so DOM-order text from a neighboring column is never merged in.
  const envelope = columnStripItems(
    items,
    anchorItem.centerX,
    headItem.centerX,
  );
  if (envelope.length === 0) return undefined;

  // Dead-zone clamp when the pointer actually landed in a vertical gap.
  if (pointerPoint) {
    const clampedEnd = clampDeadZoneEnd(index, start, end, pointerPoint.y);
    if (clampedEnd < end) end = clampedEnd;
  }

  const kept = envelope.filter((item) => item.end > start && item.start < end);
  if (kept.length === 0) return undefined;

  // Text and rects come from the kept items only, so off-column DOM-order
  // items never leak into the committed selection. Rectangles are measured
  // live from the DOM so scrolling or zooming after the index was built
  // cannot leave the committed geometry misaligned with the page rect.
  const text = kept
    .map((item) => item.text)
    .join(" ")
    .trim();
  const rects = kept.map((item) => {
    const rect = item.domNode.getBoundingClientRect();
    return {
      height: rect.height,
      left: rect.left,
      top: rect.top,
      width: rect.width,
    };
  });
  if (!text || rects.length === 0) return undefined;
  const finalStart = kept[0]!.start;
  const finalEnd = kept[kept.length - 1]!.end;

  // Text integrity: the geometry text must agree with the browser's own
  // selection after normalization. When a dead-zone clamp trimmed the range,
  // the geometry text is the browser text's trimmed prefix and is trusted;
  // otherwise the geometry text wins. Only when they genuinely diverge do we
  // fall back to the browser text (honest degradation) with geometry rects.
  const browserText = range.toString().trim();
  const geometryNormalized = normalizeForComparison(text);
  const browserNormalized = normalizeForComparison(browserText);
  const geometryIsPrefix =
    geometryNormalized.length > 0 &&
    browserNormalized.startsWith(geometryNormalized);
  const finalText =
    geometryNormalized === browserNormalized || geometryIsPrefix
      ? text
      : browserText || text;

  // Overshoot guard: when the new selection extends a previous stable one
  // (shares an endpoint) and grows dramatically beyond it while jumping
  // vertically, reject the commit to avoid crystallizing a flicker/overshoot.
  // A brand-new selection (no shared endpoint) is always allowed.
  if (previous) {
    const sharesStart = start === previous.start;
    const sharesEnd = end === previous.end;
    if (sharesStart || sharesEnd) {
      const previousLength = previous.text.length;
      const threshold = Math.max(
        previousLength * OVERSHOOT_LENGTH_FACTOR,
        previousLength + OVERSHOOT_ABSOLUTE_PADDING,
      );
      if (
        finalText.length > threshold &&
        Math.abs(previous.end - finalEnd) > threshold
      ) {
        return undefined;
      }
    }
  }

  return { start: finalStart, end: finalEnd, text: finalText, rects };
}
