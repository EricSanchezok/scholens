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

type IndexedCharacter = ReaderSearchTextPosition | undefined;

function buildSearchablePageText(textItems: string[]) {
  const characters: IndexedCharacter[] = [];
  let text = "";

  textItems.forEach((item, itemIndex) => {
    if (
      itemIndex > 0 &&
      text.length > 0 &&
      !/\s$/u.test(text) &&
      !/^\s/u.test(item)
    ) {
      text += " ";
      characters.push(undefined);
    }
    for (let offset = 0; offset < item.length; offset += 1) {
      text += item[offset];
      characters.push({ itemIndex, offset });
    }
  });

  return { characters, normalizedText: text.toLocaleLowerCase() };
}

function resolveMatchBoundary(
  characters: IndexedCharacter[],
  start: number,
  end: number,
) {
  const begin = characters.slice(start, end).find(Boolean);
  const last = characters
    .slice(start, end)
    .findLast((character): character is ReaderSearchTextPosition =>
      Boolean(character),
    );
  if (!begin || !last) return undefined;
  return {
    begin,
    end: { itemIndex: last.itemIndex, offset: last.offset + 1 },
  };
}

export function findReaderPageSearchMatches({
  ordinalOffset,
  pageNumber,
  query,
  textItems,
}: {
  ordinalOffset: number;
  pageNumber: number;
  query: string;
  textItems: string[];
}): ReaderSearchMatch[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  if (!normalizedQuery) return [];
  const { characters, normalizedText } = buildSearchablePageText(textItems);
  const matches: ReaderSearchMatch[] = [];
  let cursor = 0;

  while ((cursor = normalizedText.indexOf(normalizedQuery, cursor)) >= 0) {
    const end = cursor + normalizedQuery.length;
    const boundary = resolveMatchBoundary(characters, cursor, end);
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
