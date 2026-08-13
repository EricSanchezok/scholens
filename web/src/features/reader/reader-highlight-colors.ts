export const readerHighlightColors = [
  "yellow",
  "red",
  "green",
  "blue",
  "purple",
  "magenta",
  "orange",
  "gray",
] as const;

export type ReaderHighlightColor = (typeof readerHighlightColors)[number];

export function readReaderHighlightColor(value: string): ReaderHighlightColor {
  return readerHighlightColors.includes(value as ReaderHighlightColor)
    ? (value as ReaderHighlightColor)
    : "blue";
}

export function readerHighlightColorValue(
  value: string,
): `var(--color-document-highlight-${ReaderHighlightColor})` {
  return `var(--color-document-highlight-${readReaderHighlightColor(value)})`;
}
