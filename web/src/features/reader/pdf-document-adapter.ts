import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  PDFPageProxy,
} from "pdfjs-dist";

import {
  findReaderPageSearchMatches,
  type ReaderSearchMatch,
} from "./reader-search";

let workerConfigured = false;
const activeCanvasRenders = new WeakMap<HTMLCanvasElement, Promise<void>>();

async function loadPdfJs() {
  const pdfjs = await import("pdfjs-dist");
  if (!workerConfigured) {
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/build/pdf.worker.min.mjs",
      import.meta.url,
    ).toString();
    workerConfigured = true;
  }
  return pdfjs;
}

export class PdfDocumentAdapter {
  private constructor(
    private readonly document: PDFDocumentProxy,
    private readonly loadingTask: PDFDocumentLoadingTask,
  ) {}

  static async open(getFreshUrl: () => Promise<string>) {
    const pdfjs = await loadPdfJs();
    let latestTask: PDFDocumentLoadingTask | undefined;
    let previousError: unknown;

    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        latestTask = pdfjs.getDocument({
          url: await getFreshUrl(),
        });
        const document = await latestTask.promise;
        return new PdfDocumentAdapter(document, latestTask);
      } catch (error) {
        previousError = error;
        await latestTask?.destroy();
      }
    }
    throw previousError;
  }

  get pageCount() {
    return this.document.numPages;
  }

  get metadata() {
    return this.document.getMetadata();
  }

  getPage(pageNumber: number) {
    return this.document.getPage(pageNumber);
  }

  async resolveDestination(destination: unknown) {
    const explicit =
      typeof destination === "string"
        ? await this.document.getDestination(destination)
        : destination;
    if (!Array.isArray(explicit) || explicit.length === 0) return undefined;
    const reference = explicit[0];
    if (typeof reference === "number") return reference + 1;
    return (await this.document.getPageIndex(reference)) + 1;
  }

  async search(query: string): Promise<ReaderSearchMatch[]> {
    if (!query.trim()) return [];
    const results: ReaderSearchMatch[] = [];
    for (let pageNumber = 1; pageNumber <= this.pageCount; pageNumber += 1) {
      const page = await this.getPage(pageNumber);
      const content = await page.getTextContent();
      results.push(
        ...findReaderPageSearchMatches({
          ordinalOffset: results.length,
          pageNumber,
          query,
          textItems: content.items.map((item) =>
            "str" in item ? item.str : "",
          ),
        }),
      );
    }
    return results;
  }

  destroy() {
    return this.loadingTask.destroy();
  }
}

export function renderPdfPage({
  activeSearchMatchId,
  annotationLinkClassName,
  annotationLinkLabel,
  annotationLayer,
  canvas,
  onInternalDestination,
  page,
  scale,
  searchMatches,
  textLayer,
}: {
  activeSearchMatchId?: string;
  annotationLinkClassName: string;
  annotationLinkLabel: string;
  annotationLayer: HTMLDivElement;
  canvas: HTMLCanvasElement;
  onInternalDestination: (destination: unknown) => void;
  page: PDFPageProxy;
  scale: number;
  searchMatches: ReaderSearchMatch[];
  textLayer: HTMLDivElement;
}) {
  let cancelled = false;
  let cancelCanvasRender: (() => void) | undefined;
  let cancelTextRender: (() => void) | undefined;

  function assertActive() {
    if (cancelled) {
      throw new DOMException("PDF page render cancelled", "AbortError");
    }
  }

  const promise = (async () => {
    const pdfjs = await loadPdfJs();
    assertActive();
    await activeCanvasRenders.get(canvas);
    assertActive();
    const viewport = page.getViewport({ scale });
    const outputScale = window.devicePixelRatio || 1;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("Canvas 2D context is unavailable");

    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;

    const renderTask = page.render({
      canvas,
      canvasContext: context,
      transform:
        outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      viewport,
    });
    cancelCanvasRender = () => renderTask.cancel();
    const canvasSettled = renderTask.promise.then(
      () => undefined,
      () => undefined,
    );
    activeCanvasRenders.set(canvas, canvasSettled);
    void canvasSettled.finally(() => {
      if (activeCanvasRenders.get(canvas) === canvasSettled) {
        activeCanvasRenders.delete(canvas);
      }
    });
    assertActive();

    textLayer.replaceChildren();
    textLayer.style.width = `${viewport.width}px`;
    textLayer.style.height = `${viewport.height}px`;
    textLayer.style.setProperty("--scale-factor", `${viewport.scale}`);
    textLayer.style.setProperty("--user-unit", "1");
    textLayer.style.setProperty("--total-scale-factor", `${viewport.scale}`);
    const textContent = await page.getTextContent();
    assertActive();
    const textRenderer = new pdfjs.TextLayer({
      container: textLayer,
      textContentSource: textContent,
      viewport,
    });
    cancelTextRender = () => textRenderer.cancel();

    annotationLayer.replaceChildren();
    annotationLayer.style.width = `${viewport.width}px`;
    annotationLayer.style.height = `${viewport.height}px`;
    const annotations = await page.getAnnotations({ intent: "display" });
    assertActive();
    for (const annotation of annotations) {
      if (!annotation.rect || (!annotation.url && !annotation.dest)) continue;
      const [pointX1, pointY1] = viewport.convertToViewportPoint(
        annotation.rect[0],
        annotation.rect[1],
      );
      const [pointX2, pointY2] = viewport.convertToViewportPoint(
        annotation.rect[2],
        annotation.rect[3],
      );
      const [x1, y1, x2, y2] = [pointX1, pointY1, pointX2, pointY2];
      const link = document.createElement("a");
      link.setAttribute("aria-label", annotationLinkLabel);
      link.className = `absolute block ${annotationLinkClassName}`;
      link.style.left = `${Math.min(x1, x2)}px`;
      link.style.top = `${Math.min(y1, y2)}px`;
      link.style.width = `${Math.abs(x2 - x1)}px`;
      link.style.height = `${Math.abs(y2 - y1)}px`;
      if (annotation.url) {
        link.href = annotation.url;
        link.rel = "noreferrer noopener";
        link.target = "_blank";
      } else {
        link.href = "#";
        link.addEventListener("click", (event) => {
          event.preventDefault();
          onInternalDestination(annotation.dest);
        });
      }
      annotationLayer.append(link);
    }

    await Promise.all([renderTask.promise, textRenderer.render()]);
    assertActive();
    const fragments = new Map<
      number,
      Array<{
        active: boolean;
        end: number;
        matchId: string;
        start: number;
      }>
    >();
    for (const match of searchMatches) {
      for (
        let itemIndex = match.begin.itemIndex;
        itemIndex <= match.end.itemIndex;
        itemIndex += 1
      ) {
        const content = textRenderer.textContentItemsStr[itemIndex] ?? "";
        const start =
          itemIndex === match.begin.itemIndex ? match.begin.offset : 0;
        const end =
          itemIndex === match.end.itemIndex ? match.end.offset : content.length;
        if (end <= start) continue;
        const itemFragments = fragments.get(itemIndex) ?? [];
        itemFragments.push({
          active: match.id === activeSearchMatchId,
          end,
          matchId: match.id,
          start,
        });
        fragments.set(itemIndex, itemFragments);
      }
    }

    let activeSearchElement: HTMLElement | undefined;
    for (const [itemIndex, itemFragments] of fragments) {
      const element = textRenderer.textDivs[itemIndex];
      const content = textRenderer.textContentItemsStr[itemIndex] ?? "";
      if (!element) continue;
      element.replaceChildren();
      let cursor = 0;
      for (const fragment of itemFragments.sort(
        (left, right) => left.start - right.start,
      )) {
        if (fragment.start > cursor) {
          element.append(
            document.createTextNode(content.slice(cursor, fragment.start)),
          );
        }
        const highlight = document.createElement("span");
        highlight.className = "pdf-search-match";
        highlight.dataset.searchMatchId = fragment.matchId;
        if (fragment.active) {
          highlight.dataset.searchMatchCurrent = "true";
          activeSearchElement ??= highlight;
        }
        highlight.append(
          document.createTextNode(content.slice(fragment.start, fragment.end)),
        );
        element.append(highlight);
        cursor = fragment.end;
      }
      if (cursor < content.length) {
        element.append(document.createTextNode(content.slice(cursor)));
      }
    }

    return {
      activeSearchElement,
      height: viewport.height,
      width: viewport.width,
    };
  })();

  return {
    cancel() {
      cancelled = true;
      cancelCanvasRender?.();
      cancelTextRender?.();
    },
    promise,
  };
}
