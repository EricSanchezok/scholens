import {
  normalizeReaderSelectionRects,
  type ClientRect,
  type NormalizedSelectionRect,
} from "./selection/rect-normalization";

type NormalizedText = {
  ends: number[];
  starts: number[];
  value: string;
};

function normalizeWithMap(value: string): NormalizedText {
  let normalized = "";
  const starts: number[] = [];
  const ends: number[] = [];
  let pendingSpace = false;

  for (let offset = 0; offset < value.length;) {
    const codePoint = value.codePointAt(offset);
    if (codePoint === undefined) break;
    const character = String.fromCodePoint(codePoint);
    const nextOffset = offset + character.length;
    if (character === "\u00ad") {
      offset = nextOffset;
      continue;
    }
    if (/\s/u.test(character)) {
      if (normalized && !pendingSpace) {
        normalized += " ";
        starts.push(offset);
        ends.push(nextOffset);
      }
      pendingSpace = true;
      offset = nextOffset;
      continue;
    }
    pendingSpace = false;
    const folded = character.normalize("NFKC");
    for (let index = 0; index < folded.length; index += 1) {
      normalized += folded[index];
      starts.push(offset);
      ends.push(nextOffset);
    }
    offset = nextOffset;
  }

  if (normalized.endsWith(" ")) {
    normalized = normalized.slice(0, -1);
    starts.pop();
    ends.pop();
  }
  return { ends, starts, value: normalized };
}

function textNodes(root: HTMLElement): Text[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let node = walker.nextNode();
  while (node) {
    nodes.push(node as Text);
    node = walker.nextNode();
  }
  return nodes;
}

function pointAt(nodes: Text[], offset: number) {
  let remaining = offset;
  for (const node of nodes) {
    if (remaining <= node.data.length) {
      return { node, offset: remaining };
    }
    remaining -= node.data.length;
  }
  const last = nodes.at(-1);
  return last ? { node: last, offset: last.data.length } : undefined;
}

/**
 * Resolve a server-side parsed-text anchor against the PDF.js text layer.
 *
 * The server intentionally stores offsets rather than fragile PDF geometry.
 * Once PDF.js has painted a page, this function maps the quote back to DOM
 * text nodes and returns the same normalized rectangles used by user
 * selection. It is deliberately read-only: unresolved anchors are omitted so
 * the Reader never paints a misleading mark.
 */
export function resolveReaderParsedTextRects({
  pageElement,
  quoteText,
  textLayer,
}: {
  pageElement: HTMLElement;
  quoteText: string;
  textLayer: HTMLElement;
}): NormalizedSelectionRect[] {
  if (!quoteText.trim()) return [];
  const nodes = textNodes(textLayer);
  if (nodes.length === 0) return [];
  const rawText = nodes.map((node) => node.data).join("");
  const haystack = normalizeWithMap(rawText);
  const needle = normalizeWithMap(quoteText).value;
  if (!needle) return [];
  const matchStart = haystack.value.indexOf(needle);
  if (matchStart < 0) return [];
  const matchEnd = matchStart + needle.length - 1;
  const rawStart = haystack.starts[matchStart];
  const rawEnd = haystack.ends[matchEnd];
  if (rawStart === undefined || rawEnd === undefined || rawEnd <= rawStart) {
    return [];
  }

  const range = document.createRange();
  const start = pointAt(nodes, rawStart);
  const end = pointAt(nodes, rawEnd);
  if (!start || !end) return [];
  range.setStart(start.node, start.offset);
  range.setEnd(end.node, end.offset);
  const pageRect = pageElement.getBoundingClientRect();
  const clientRects: ClientRect[] = Array.from(range.getClientRects()).map(
    (rect) => ({
      height: rect.height,
      left: rect.left,
      top: rect.top,
      width: rect.width,
    }),
  );
  return normalizeReaderSelectionRects(pageRect, clientRects);
}
