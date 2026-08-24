const CONTROL_CHARACTERS =
  /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\uFFFD]/g;

const BLOCK_HTML_TAGS =
  /<\/?(?:address|article|aside|blockquote|div|dl|dt|dd|figcaption|figure|footer|form|h[1-6]|header|hr|li|main|nav|ol|p|pre|section|table|tbody|td|tfoot|th|thead|tr|ul)\b[^>]*>/gi;

const HTML_ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  lt: "<",
  nbsp: " ",
  quot: '"',
};

function decodeHtmlEntities(value: string) {
  return value.replace(
    /&(#(?:x[\da-f]+|\d+)|amp|apos|gt|lt|nbsp|quot);/gi,
    (entity, name: string) => {
      const normalized = name.toLowerCase();
      if (normalized.startsWith("#x")) {
        const point = Number.parseInt(normalized.slice(2), 16);
        return Number.isFinite(point) &&
          point <= 0x10ffff &&
          !(point >= 0xd800 && point <= 0xdfff)
          ? String.fromCodePoint(point)
          : "";
      }
      if (normalized.startsWith("#")) {
        const point = Number.parseInt(normalized.slice(1), 10);
        return Number.isFinite(point) &&
          point <= 0x10ffff &&
          !(point >= 0xd800 && point <= 0xdfff)
          ? String.fromCodePoint(point)
          : "";
      }
      return HTML_ENTITIES[normalized] ?? entity;
    },
  );
}

/**
 * Removes unsafe or unsupported academic HTML while preserving Markdown
 * structure for the Reader renderer.
 */
export function sanitizeAcademicMarkdown(markdown: string) {
  return markdown
    .replace(/<!--[\s\S]*?(?:-->|$)/g, "")
    .replace(
      /<(?:script|style)\b[^>]*>[\s\S]*?(?:<\/(?:script|style)>|$)/gi,
      "",
    )
    .replace(/<sup>\s*([^<]+?)\s*<\/sup>/gi, (_, value: string) =>
      value.trim() ? `$^{${value.trim()}}$` : "",
    )
    .replace(/<sub>\s*([^<]+?)\s*<\/sub>/gi, (_, value: string) =>
      value.trim() ? `$_{${value.trim()}}$` : "",
    )
    .replace(
      /<img\b[^>]*\balt\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))[^>]*>/gi,
      (_, doubleQuoted: string, singleQuoted: string, unquoted: string) =>
        doubleQuoted || singleQuoted || unquoted || "",
    )
    .replace(/<br\s*\/?>/gi, "  \n")
    .replace(BLOCK_HTML_TAGS, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(CONTROL_CHARACTERS, "");
}

/** Converts academic Markdown and tolerated HTML into compact display text. */
export function academicMarkdownToPlainText(markdown: string) {
  return sanitizeAcademicMarkdown(
    decodeHtmlEntities(sanitizeAcademicMarkdown(markdown)),
  )
    .replace(CONTROL_CHARACTERS, "")
    .replace(/^\s*(`{3,}|~{3,}).*$/gm, "")
    .replace(/^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$/gm, "")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)/gm, "")
    .replace(/\|/g, " ")
    .replace(/\\([\\`*_[\]{}()#+.!|>$~-])/g, "$1")
    .replace(/[`*_#$>[\]{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}
