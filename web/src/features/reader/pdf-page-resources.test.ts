import type { PDFPageProxy } from "pdfjs-dist";
import { describe, expect, it, vi } from "vitest";

import { pdfBitmapScale, retainPdfPage } from "./pdf-page-resources";

describe("PDF page resource ownership", () => {
  it("keeps an overlapping viewport/thumbnail/search lease alive", () => {
    const cleanup = vi.fn();
    const page = { cleanup } as unknown as PDFPageProxy;
    const viewport = retainPdfPage(page);
    const thumbnail = retainPdfPage(page);
    const search = retainPdfPage(page);
    viewport();
    viewport();
    thumbnail();
    expect(cleanup).not.toHaveBeenCalled();
    search();
    expect(cleanup).toHaveBeenCalledOnce();
    retainPdfPage(page)();
    expect(cleanup).toHaveBeenCalledTimes(2);
  });

  it("caps bitmap memory without changing CSS page geometry", () => {
    for (const [width, height, dpr] of [
      [600, 800, 2],
      [3000, 4000, 3],
      [12000, 24000, 4],
    ]) {
      const scale = pdfBitmapScale(width!, height!, dpr!);
      expect(
        Math.floor(width! * scale) * Math.floor(height! * scale),
      ).toBeLessThanOrEqual(4_000_000);
      expect(scale).toBeGreaterThan(0);
    }
    expect(pdfBitmapScale(600, 800, 2)).toBe(2);
  });
});
