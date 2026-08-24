import type { Route } from "next";

import type { PaperCollectionItem } from "@/features/paper-collection";
import { academicMarkdownToPlainText } from "@/lib/content/academic-text";
import type { PaperSearchResult } from "./api";

export const PAPER_SEARCH_EXCERPT_LIMIT = 320;

const graphemeSegmenter = new Intl.Segmenter(undefined, {
  granularity: "grapheme",
});

function truncateExcerpt(value: string) {
  const graphemes = Array.from(
    graphemeSegmenter.segment(value),
    ({ segment }) => segment,
  );
  if (graphemes.length <= PAPER_SEARCH_EXCERPT_LIMIT) return value;
  const windowSize = PAPER_SEARCH_EXCERPT_LIMIT - 1;
  const window = graphemes.slice(0, windowSize);
  let boundary = -1;
  for (let index = window.length - 1; index >= 0; index -= 1) {
    if (/\s/u.test(window[index] ?? "")) {
      boundary = index;
      break;
    }
  }
  const minimumWordBoundary = Math.floor(windowSize * 0.75);
  const excerpt = window
    .slice(0, boundary >= minimumWordBoundary ? boundary : window.length)
    .join("")
    .trimEnd();
  return `${excerpt}…`;
}

export function paperSearchExcerpt(
  paper: Pick<PaperSearchResult, "abstract" | "snippets" | "summary">,
) {
  const candidates = [
    ...(paper.snippets ?? []).map(({ text }) => text),
    paper.summary,
    paper.abstract,
  ];

  for (const candidate of candidates) {
    if (!candidate) continue;
    const excerpt = academicMarkdownToPlainText(candidate);
    if (excerpt) return truncateExcerpt(excerpt);
  }
  return undefined;
}

export function toPaperSearchCollectionItem(
  paper: PaperSearchResult,
  {
    formatDate,
    readerProjectId,
    untitled,
  }: {
    formatDate: (date: Date) => string;
    readerProjectId?: string;
    untitled: string;
  },
): PaperCollectionItem {
  return {
    abstract: paper.abstract ?? undefined,
    addedAt: formatDate(new Date(paper.created_at)),
    authors: paper.authors ?? [],
    doi: paper.doi ?? undefined,
    href: (readerProjectId
      ? `/reader/${paper.document_id}?project=${readerProjectId}`
      : `/reader/${paper.document_id}`) as Route,
    id: paper.document_id,
    inLibrary: Boolean(paper.personal_status),
    keywords: paper.keywords ?? [],
    lastOpened: paper.personal_last_accessed_at
      ? formatDate(new Date(paper.personal_last_accessed_at))
      : undefined,
    previewUrl: paper.preview_url ?? undefined,
    publication: [
      paper.journal,
      paper.publish_date
        ? new Date(paper.publish_date).getUTCFullYear().toString()
        : undefined,
    ]
      .filter(Boolean)
      .join(" · "),
    snippet: paperSearchExcerpt(paper),
    status: paper.personal_status ?? undefined,
    summary: paper.summary ?? undefined,
    tags: paper.personal_tags ?? [],
    title: paper.title || untitled,
  };
}
