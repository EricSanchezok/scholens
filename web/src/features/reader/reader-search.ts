export type ReaderSearchMatch = {
  begin: ReaderSearchTextPosition;
  end: ReaderSearchTextPosition;
  id: string;
  ordinal: number;
  pageMatchIndex: number;
  pageNumber: number;
};

export type ReaderSearchTextPosition = {
  itemIndex: number;
  offset: number;
};

type TextSpan = {
  itemIndex: number;
  start: number;
  end: number;
  source: string;
  normalized: string;
};

function buildSearchablePageText(textItems: string[]) {
  const spans: TextSpan[] = [];
  const parts: string[] = [];
  let length = 0;
  let previous = "";
  textItems.forEach((source, itemIndex) => {
    if (length > 0 && !/\s$/u.test(previous) && !/^\s/u.test(source)) {
      parts.push(" ");
      length += 1;
    }
    const normalized = source.toLocaleLowerCase();
    if (source)
      spans.push({
        itemIndex,
        start: length,
        end: length + normalized.length,
        source,
        normalized,
      });
    parts.push(normalized);
    length += normalized.length;
    previous = normalized || " ";
  });
  return { spans, normalizedText: parts.join("") };
}

function sourceOffset(span: TextSpan, offset: number, end: boolean) {
  if (span.source.length === span.normalized.length) return offset;
  let source = 0;
  let normalized = 0;
  for (const character of span.source) {
    const next = normalized + character.toLocaleLowerCase().length;
    if (offset < next)
      return source + (end && offset > normalized ? character.length : 0);
    normalized = next;
    source += character.length;
  }
  return source;
}

function spanAt(spans: TextSpan[], position: number) {
  let low = 0;
  let high = spans.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (spans[middle]!.end <= position) low = middle + 1;
    else high = middle;
  }
  return low;
}

function resolveMatchBoundary(spans: TextSpan[], start: number, end: number) {
  const first = spans[spanAt(spans, start)];
  let lastIndex = Math.min(spanAt(spans, end - 1), spans.length - 1);
  if (spans[lastIndex] && spans[lastIndex]!.start >= end) lastIndex -= 1;
  const last = spans[lastIndex];
  if (!first || !last || first.start >= end || last.end <= start)
    return undefined;
  return {
    begin: {
      itemIndex: first.itemIndex,
      offset: sourceOffset(first, Math.max(0, start - first.start), false),
    },
    end: {
      itemIndex: last.itemIndex,
      offset: sourceOffset(
        last,
        Math.min(last.normalized.length, end - last.start),
        true,
      ),
    },
  };
}

export function findReaderPageSearchMatches({
  ordinalOffset,
  maxMatches = 1_001,
  pageNumber,
  query,
  textItems,
}: {
  ordinalOffset: number;
  maxMatches?: number;
  pageNumber: number;
  query: string;
  textItems: string[];
}): ReaderSearchMatch[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  if (!normalizedQuery) return [];
  const { spans, normalizedText } = buildSearchablePageText(textItems);
  const matches: ReaderSearchMatch[] = [];
  let cursor = 0;

  while (
    matches.length < maxMatches &&
    (cursor = normalizedText.indexOf(normalizedQuery, cursor)) >= 0
  ) {
    const end = cursor + normalizedQuery.length;
    const boundary = resolveMatchBoundary(spans, cursor, end);
    if (boundary) {
      const pageMatchIndex = matches.length;
      matches.push({
        ...boundary,
        id: `${pageNumber}:${pageMatchIndex}`,
        ordinal: ordinalOffset + pageMatchIndex,
        pageMatchIndex,
        pageNumber,
      });
    }
    cursor = end;
  }

  return matches;
}

export function moveReaderSearchCursor(
  currentIndex: number,
  matchCount: number,
  direction: -1 | 1,
) {
  if (matchCount === 0) return -1;
  return (currentIndex + direction + matchCount) % matchCount;
}
