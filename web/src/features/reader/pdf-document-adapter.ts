import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  PDFPageProxy,
} from "pdfjs-dist";

import {
  findReaderPageSearchMatches,
  type ReaderSearchMatch,
} from "./reader-search";
import { clientEnvironment } from "@/lib/env/client";
import { pdfBitmapScale, retainPdfPage } from "./pdf-page-resources";

let workerConfigured = false;
const activeCanvasRenders = new WeakMap<HTMLCanvasElement, Promise<void>>();
const canvasOwners = new WeakMap<HTMLCanvasElement, symbol>();
const pdfjsRelease = clientEnvironment.NEXT_PUBLIC_RELEASE_SHA;
export const PDFJS_WASM_URL = `/pdfjs/wasm/${encodeURIComponent(pdfjsRelease)}/`;
const requiredCodecAssets = [
  "jbig2.wasm",
  "openjpeg.wasm",
  "qcms_bg.wasm",
  "jbig2_nowasm_fallback.js",
  "openjpeg_nowasm_fallback.js",
] as const;

type PdfJsAssetManifest = {
  files: Record<string, { sha256: string; size: number }>;
  pdfjs_version: string;
  release: string;
  schema: 1;
};

export class PdfJsAssetsUnavailableError extends Error {
  readonly asset: string;

  constructor(asset: string) {
    super(`PDF.js codec asset is unavailable: ${asset}`);
    this.asset = asset;
    this.name = "PdfJsAssetsUnavailableError";
  }
}

let codecAssetsPromise: Promise<void> | undefined;

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

async function ensurePdfJsCodecAssets(pdfjs: { version: string }) {
  if (!codecAssetsPromise) {
    codecAssetsPromise = (async () => {
      let manifestResponse: Response;
      try {
        manifestResponse = await fetch(`${PDFJS_WASM_URL}manifest.json`, {
          cache: "no-store",
        });
      } catch {
        throw new PdfJsAssetsUnavailableError("manifest.json");
      }
      if (!manifestResponse.ok) {
        throw new PdfJsAssetsUnavailableError("manifest.json");
      }

      let manifest: PdfJsAssetManifest;
      try {
        manifest = (await manifestResponse.json()) as PdfJsAssetManifest;
      } catch {
        throw new PdfJsAssetsUnavailableError("manifest.json");
      }
      if (
        manifest.schema !== 1 ||
        manifest.release !== pdfjsRelease ||
        manifest.pdfjs_version !== pdfjs.version ||
        !manifest.files
      ) {
        throw new PdfJsAssetsUnavailableError("manifest.json");
      }

      await Promise.all(
        requiredCodecAssets.map(async (asset) => {
          if (!manifest.files[asset]) {
            throw new PdfJsAssetsUnavailableError(asset);
          }
          let response: Response;
          try {
            response = await fetch(`${PDFJS_WASM_URL}${asset}`, {
              cache: "no-store",
              method: "HEAD",
            });
          } catch {
            throw new PdfJsAssetsUnavailableError(asset);
          }
          if (!response.ok) {
            throw new PdfJsAssetsUnavailableError(asset);
          }
          if (
            asset.endsWith(".wasm") &&
            !response.headers
              .get("content-type")
              ?.toLowerCase()
              .includes("application/wasm")
          ) {
            throw new PdfJsAssetsUnavailableError(asset);
          }
        }),
      );
    })();
  }
  try {
    await codecAssetsPromise;
  } catch (error) {
    codecAssetsPromise = undefined;
    throw error;
  }
}

export type PdfSearchResult = {
  matches: ReaderSearchMatch[];
  limited: boolean;
};
const SEARCH_MATCH_LIMIT = 1_000;
const SEARCH_CACHE_BYTES = 2 * 1024 * 1024;

export class PdfDocumentAdapter {
  private readonly searchCache = new Map<
    number,
    { items: string[]; bytes: number }
  >();
  private searchCacheBytes = 0;
  private searchController: AbortController | undefined;

  private constructor(
    private readonly document: PDFDocumentProxy,
    private readonly loadingTask: PDFDocumentLoadingTask,
  ) {}

  static async open(getFreshUrl: () => Promise<string>) {
    const pdfjs = await loadPdfJs();
    await ensurePdfJsCodecAssets(pdfjs);
    let latestTask: PDFDocumentLoadingTask | undefined;
    let previousError: unknown;

    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        latestTask = pdfjs.getDocument({
          url: await getFreshUrl(),
          wasmUrl: PDFJS_WASM_URL,
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

  private async searchText(pageNumber: number, signal: AbortSignal) {
    signal.throwIfAborted();
    const cached = this.searchCache.get(pageNumber);
    if (cached) {
      this.searchCache.delete(pageNumber);
      this.searchCache.set(pageNumber, cached);
      return cached.items;
    }
    const page = await this.getPage(pageNumber);
    signal.throwIfAborted();
    const release = retainPdfPage(page);
    const reader = page.streamTextContent().getReader();
    const cancel = () => {
      void reader.cancel().catch(() => undefined);
    };
    signal.addEventListener("abort", cancel, { once: true });
    const items: string[] = [];
    let bytes = 0;
    try {
      while (true) {
        signal.throwIfAborted();
        const { value, done } = await reader.read();
        signal.throwIfAborted();
        if (done) break;
        for (const item of value.items) {
          const text = "str" in item ? item.str : "";
          bytes += text.length * 2 + 64;
          if (bytes > 8 * 1024 * 1024) throw new Error("pdf_search_page_limit");
          items.push(text);
        }
      }
      if (bytes <= SEARCH_CACHE_BYTES) {
        while (
          this.searchCache.size >= 8 ||
          this.searchCacheBytes + bytes > SEARCH_CACHE_BYTES
        ) {
          const oldest = this.searchCache.keys().next().value;
          if (oldest === undefined) break;
          this.searchCacheBytes -= this.searchCache.get(oldest)!.bytes;
          this.searchCache.delete(oldest);
        }
        this.searchCache.set(pageNumber, { items, bytes });
        this.searchCacheBytes += bytes;
      }
      return items;
    } finally {
      signal.removeEventListener("abort", cancel);
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
      release();
    }
  }

  async search(query: string, signal?: AbortSignal): Promise<PdfSearchResult> {
    this.searchController?.abort();
    const controller = new AbortController();
    this.searchController = controller;
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    const matches: ReaderSearchMatch[] = [];
    try {
      if (!query.trim()) return { matches, limited: false };
      for (let pageNumber = 1; pageNumber <= this.pageCount; pageNumber += 1) {
        controller.signal.throwIfAborted();
        const textItems = await this.searchText(pageNumber, controller.signal);
        matches.push(
          ...findReaderPageSearchMatches({
            ordinalOffset: matches.length,
            maxMatches: SEARCH_MATCH_LIMIT + 1 - matches.length,
            pageNumber,
            query,
            textItems,
          }),
        );
        if (matches.length > SEARCH_MATCH_LIMIT)
          return {
            matches: matches.slice(0, SEARCH_MATCH_LIMIT),
            limited: true,
          };
        // Yield between pages so typing/cancellation and input feedback can run.
        await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
      }
      return { matches, limited: false };
    } finally {
      signal?.removeEventListener("abort", abort);
      if (this.searchController === controller)
        this.searchController = undefined;
    }
  }

  destroy() {
    this.searchController?.abort();
    this.searchCache.clear();
    this.searchCacheBytes = 0;
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
  const owner = Symbol("pdf-render");
  canvasOwners.set(canvas, owner);
  const releasePage = retainPdfPage(page);
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
    const outputScale = pdfBitmapScale(
      viewport.width,
      viewport.height,
      window.devicePixelRatio || 1,
    );
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
      return Promise.allSettled([
        promise,
        activeCanvasRenders.get(canvas),
      ]).then(() => {
        releasePage();
        // A new zoom/render may already own this same canvas.
        if (canvasOwners.get(canvas) !== owner) return false;
        canvasOwners.delete(canvas);
        canvas.width = 0;
        canvas.height = 0;
        textLayer.replaceChildren();
        annotationLayer.replaceChildren();
        return true;
      });
    },
    promise,
  };
}
