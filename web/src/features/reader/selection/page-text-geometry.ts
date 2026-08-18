/**
 * Page text geometry index.
 *
 * Builds a read-only, span-level model of one rendered PDF.js text layer so
 * selection commit normalization has a single geometric source of truth:
 * every selectable character belongs to exactly one item with a client-space
 * rectangle and a page-ordered character offset.
 *
 * The index is rebuilt whenever the text layer DOM changes (render, zoom,
 * search-highlight rewrite) and is never mutated afterwards.
 */

export type GeometryPoint = {
  x: number;
  y: number;
};

export type GeometryRect = {
  height: number;
  left: number;
  top: number;
  width: number;
};

export type GeometryItem = {
  /** The span element that owns this item's text. */
  domNode: HTMLElement;
  /** Character offset of this item's first character in page order. */
  start: number;
  /** Character offset just past this item's last character. */
  end: number;
  /** Visible text in page order (without browser-injected spaces). */
  text: string;
  /** Client-space rectangle of the item's rendered box. */
  rect: GeometryRect;
  /** Horizontal center of the rendered box. */
  centerX: number;
  /** Vertical center of the rendered box. */
  centerY: number;
};

export type PageTextGeometryIndex = {
  pageNumber: number;
  /** Total number of selectable characters in page order. */
  length: number;
  /** Ordered selectable items. */
  items: GeometryItem[];
  /** The text layer container the index was built from. */
  textLayer: HTMLElement;
  /** Monotonic version bumped every time the index is rebuilt. */
  version: number;
};

function textContentOfElement(element: HTMLElement): string {
  return element.textContent ?? "";
}

function isSelectableSpan(element: Element): boolean {
  if (element.tagName !== "SPAN") return false;
  if (element.classList.contains("endOfContent")) return false;
  if (element.getAttribute("role") === "img") return false;
  return Boolean(textContentOfElement(element as HTMLElement).trim());
}

export function buildPageTextGeometryIndex(
  textLayer: HTMLElement,
  pageNumber: number,
  version: number,
): PageTextGeometryIndex {
  const items: GeometryItem[] = [];
  let offset = 0;
  // Query all spans, but skip nested ones (search highlights, role=img
  // glyphs) so each selectable text item is represented exactly once.
  for (const span of Array.from(
    textLayer.querySelectorAll<HTMLElement>("span"),
  )) {
    if (span.parentElement?.closest("span")) continue;
    if (!isSelectableSpan(span)) continue;
    const text = textContentOfElement(span);
    const rect = span.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    items.push({
      domNode: span,
      start: offset,
      end: offset + text.length,
      text,
      rect,
      centerX: rect.left + rect.width / 2,
      centerY: rect.top + rect.height / 2,
    });
    offset += text.length;
  }
  return {
    pageNumber,
    length: offset,
    items,
    textLayer,
    version,
  };
}

/** Euclidean distance from a point to a rectangle (0 when inside). */
export function pointRectDistance(point: GeometryPoint, rect: GeometryRect) {
  const dx = Math.max(
    rect.left - point.x,
    0,
    point.x - (rect.left + rect.width),
  );
  const dy = Math.max(
    rect.top - point.y,
    0,
    point.y - (rect.top + rect.height),
  );
  return Math.hypot(dx, dy);
}

/**
 * Nearest item to a client point. Returns undefined when the index has no
 * items.
 */
export function hitTestNearest(
  index: PageTextGeometryIndex,
  point: GeometryPoint,
): GeometryItem | undefined {
  if (index.items.length === 0) return undefined;
  let best: GeometryItem | undefined;
  let bestDistance = Infinity;
  for (const item of index.items) {
    const distance = pointRectDistance(point, item.rect);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = item;
    }
  }
  return best;
}

/**
 * Map a DOM range boundary to a page-order character offset.
 *
 * - Text-node boundaries resolve to the exact character offset.
 * - Element boundaries on a selectable span map proportionally across the
 *   span's children (search highlights split text into multiple nodes).
 * - Container / sentinel / other element boundaries resolve to the nearest
 *   selectable glyph edge (start → 0, end → page length).
 */
export function mapDomBoundaryToOffset(
  index: PageTextGeometryIndex,
  node: Node,
  offset: number,
  isStart: boolean,
): number {
  const textNode = node.nodeType === Node.TEXT_NODE ? node : undefined;
  const span = textNode?.parentElement;
  if (span) {
    const item = index.items.find((candidate) => candidate.domNode === span);
    if (item) {
      const within = Math.min(Math.max(offset, 0), item.text.length);
      return item.start + within;
    }
  }
  if (node.nodeType === Node.ELEMENT_NODE) {
    const element = node as Element;
    const item = index.items.find((candidate) => candidate.domNode === element);
    if (item) {
      const children = element.childNodes.length;
      const within =
        children === 0
          ? 0
          : Math.round(
              (Math.min(Math.max(offset, 0), children) / children) *
                item.text.length,
            );
      return Math.min(Math.max(item.start + within, item.start), item.end);
    }
    const rect = element.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      const nearest = hitTestNearest(index, {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
      });
      if (nearest) {
        return isStart
          ? nearest.start
          : Math.round(nearest.start + nearest.text.length / 2);
      }
    }
  }
  return isStart ? 0 : index.length;
}

/** Select the items whose page-order range intersects [start, end). */
export function itemsForOffsets(
  index: PageTextGeometryIndex,
  start: number,
  end: number,
): GeometryItem[] {
  return index.items.filter((item) => item.start < end && item.end > start);
}

/** Build the page-order text for a range, joining items with single spaces. */
export function sliceText(
  index: PageTextGeometryIndex,
  start: number,
  end: number,
) {
  const from = Math.min(Math.max(start, 0), index.length);
  const to = Math.min(Math.max(end, 0), index.length);
  const parts: string[] = [];
  for (const item of itemsForOffsets(index, from, to)) {
    const itemStart = Math.max(from, item.start);
    const itemEnd = Math.min(to, item.end);
    if (itemEnd <= itemStart) continue;
    parts.push(item.text.slice(itemStart - item.start, itemEnd - item.start));
  }
  return parts.join(" ").trim();
}

/**
 * Client-space rectangles covering a page-order range, one per item. Returns
 * empty when the range contains no selectable text.
 */
export function rectsForOffsets(
  index: PageTextGeometryIndex,
  start: number,
  end: number,
): GeometryRect[] {
  const from = Math.min(Math.max(start, 0), index.length);
  const to = Math.min(Math.max(end, 0), index.length);
  const rects: GeometryRect[] = [];
  for (const item of itemsForOffsets(index, from, to)) {
    rects.push({ ...item.rect });
  }
  return rects;
}
