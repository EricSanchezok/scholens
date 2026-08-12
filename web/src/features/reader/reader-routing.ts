import type { ReaderContextPanel, ReaderDocumentSource } from "./reader-types";

export function parsePositiveInteger(value: string | null, fallback = 1) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : fallback;
}

export function readReaderPanel(
  value: string | null,
): ReaderContextPanel | undefined {
  return value === "ask" || value === "annotations" || value === "details"
    ? value
    : undefined;
}

export function readSourcePage(locator: ReaderDocumentSource["locator"]) {
  if (!locator) return undefined;
  const value = locator.page_number ?? locator.page;
  const page = typeof value === "number" ? value : Number(value);
  return Number.isInteger(page) && page > 0 ? page : undefined;
}
