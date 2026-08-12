import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  PDFPageProxy,
} from "pdfjs-dist";

export type PdfOutlineEntry = {
  title: string;
  destination: unknown;
  children: PdfOutlineEntry[];
};

export type PdfSearchResult = {
  pageNumber: number;
  count: number;
};

let workerConfigured = false;

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

function normalizeOutline(
  items: Awaited<ReturnType<PDFDocumentProxy["getOutline"]>>,
): PdfOutlineEntry[] {
  return (items ?? []).map<PdfOutlineEntry>((item) => ({
    title: item.title,
    destination: item.dest,
    children: normalizeOutline(item.items),
  }));
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

  async getOutline() {
    return normalizeOutline(await this.document.getOutline());
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

  async search(query: string): Promise<PdfSearchResult[]> {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return [];
    const results: PdfSearchResult[] = [];
    for (let pageNumber = 1; pageNumber <= this.pageCount; pageNumber += 1) {
      const page = await this.getPage(pageNumber);
      const content = await page.getTextContent();
      const text = content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ")
        .toLocaleLowerCase();
      let count = 0;
      let cursor = 0;
      while ((cursor = text.indexOf(normalized, cursor)) >= 0) {
        count += 1;
        cursor += Math.max(normalized.length, 1);
      }
      if (count > 0) results.push({ pageNumber, count });
    }
    return results;
  }

  destroy() {
    return this.loadingTask.destroy();
  }
}

export async function renderPdfPage({
  annotationLayer,
  canvas,
  onInternalDestination,
  page,
  scale,
  searchQuery,
  textLayer,
}: {
  annotationLayer: HTMLDivElement;
  canvas: HTMLCanvasElement;
  onInternalDestination: (destination: unknown) => void;
  page: PDFPageProxy;
  scale: number;
  searchQuery: string;
  textLayer: HTMLDivElement;
}) {
  const pdfjs = await loadPdfJs();
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

  textLayer.replaceChildren();
  textLayer.style.width = `${viewport.width}px`;
  textLayer.style.height = `${viewport.height}px`;
  textLayer.style.setProperty("--scale-factor", `${viewport.scale}`);
  textLayer.style.setProperty("--user-unit", "1");
  textLayer.style.setProperty("--total-scale-factor", `${viewport.scale}`);
  const textContent = await page.getTextContent();
  const textRenderer = new pdfjs.TextLayer({
    container: textLayer,
    textContentSource: textContent,
    viewport,
  });

  annotationLayer.replaceChildren();
  annotationLayer.style.width = `${viewport.width}px`;
  annotationLayer.style.height = `${viewport.height}px`;
  for (const annotation of await page.getAnnotations({ intent: "display" })) {
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
    link.className = "absolute block";
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
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
  textRenderer.textDivs.forEach((element, index) => {
    if (
      normalizedQuery &&
      textRenderer.textContentItemsStr[index]
        ?.toLocaleLowerCase()
        .includes(normalizedQuery)
    ) {
      element.dataset.searchHit = "true";
    }
  });

  return {
    cancel() {
      renderTask.cancel();
      textRenderer.cancel();
    },
    height: viewport.height,
    width: viewport.width,
  };
}
