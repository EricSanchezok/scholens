export type ReadingActivityExportPage = {
  blob: Blob;
  nextCursor?: string | null;
};

export async function collectReadingActivityCsv(
  loadPage: (input: {
    cursor?: string;
    includeHeader: boolean;
  }) => Promise<ReadingActivityExportPage>,
) {
  const chunks: BlobPart[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | undefined;
  let includeHeader = true;

  while (true) {
    const page = await loadPage({ cursor, includeHeader });
    chunks.push(page.blob);
    const nextCursor = page.nextCursor || undefined;
    if (!nextCursor) break;
    if (seenCursors.has(nextCursor)) {
      throw new Error("Reading activity export returned a repeated cursor");
    }
    seenCursors.add(nextCursor);
    cursor = nextCursor;
    includeHeader = false;
  }

  return new Blob(chunks, { type: "text/csv;charset=utf-8" });
}
