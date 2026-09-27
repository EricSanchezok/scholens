import type { PDFPageProxy } from "pdfjs-dist";

const owners = new WeakMap<PDFPageProxy, number>();

/** Search, thumbnails and the viewport share PDF.js page resources. */
export function retainPdfPage(page: PDFPageProxy) {
  owners.set(page, (owners.get(page) ?? 0) + 1);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const remaining = (owners.get(page) ?? 1) - 1;
    if (remaining > 0) owners.set(page, remaining);
    else {
      owners.delete(page);
      // PDF.js defers cleanup until any pending render/operator list settles.
      page.cleanup();
    }
  };
}

/** Bound each backing bitmap to 4M pixels, including extreme zoom and DPR. */
export function pdfBitmapScale(
  width: number,
  height: number,
  deviceScale: number,
) {
  return Math.min(
    Math.max(1, deviceScale),
    Math.sqrt(4_000_000 / Math.max(1, width * height)),
  );
}
