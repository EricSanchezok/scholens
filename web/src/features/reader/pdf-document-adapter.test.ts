import { beforeEach, describe, expect, it, vi } from "vitest";

const pdfjs = vi.hoisted(() => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: vi.fn(),
  TextLayer: vi.fn(),
  version: "6.2.108",
}));

vi.mock("pdfjs-dist", () => pdfjs);

const requiredAssets = [
  "jbig2.wasm",
  "openjpeg.wasm",
  "qcms_bg.wasm",
  "jbig2_nowasm_fallback.js",
  "openjpeg_nowasm_fallback.js",
];

function mockAssetFetch(files = requiredAssets) {
  const manifest = {
    files: Object.fromEntries(
      files.map((file) => [file, { sha256: "test", size: 1 }]),
    ),
    pdfjs_version: "6.2.108",
    release: "development",
    schema: 1,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("manifest.json")) {
        return Promise.resolve(
          new Response(JSON.stringify(manifest), {
            headers: { "content-type": "application/json" },
            status: 200,
          }),
        );
      }
      return Promise.resolve(
        new Response(null, {
          headers: {
            "content-type": url.endsWith(".wasm")
              ? "application/wasm"
              : "application/javascript",
          },
          status: init?.method === "HEAD" ? 200 : 200,
        }),
      );
    }),
  );
}

describe("PdfDocumentAdapter", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    pdfjs.getDocument.mockReset();
    pdfjs.version = "6.2.108";
    mockAssetFetch();
  });

  it("passes the release-scoped WASM URL to PDF.js", async () => {
    const document = {
      getPage: vi.fn(),
      getMetadata: vi.fn(),
      numPages: 1,
    };
    const destroy = vi.fn().mockResolvedValue(undefined);
    pdfjs.getDocument.mockReturnValue({
      destroy,
      promise: Promise.resolve(document),
    });
    const { PDFJS_WASM_URL, PdfDocumentAdapter } =
      await import("./pdf-document-adapter");

    const adapter = await PdfDocumentAdapter.open(
      vi.fn().mockResolvedValue("/signed-paper.pdf"),
    );

    expect(pdfjs.getDocument).toHaveBeenCalledWith({
      url: "/signed-paper.pdf",
      wasmUrl: PDFJS_WASM_URL,
    });
    await adapter.destroy();
    expect(destroy).toHaveBeenCalledOnce();
  });

  it("fails before fetching a signed PDF URL when a codec asset is missing", async () => {
    mockAssetFetch(requiredAssets.slice(0, -1));
    const getFreshUrl = vi.fn().mockResolvedValue("/signed-paper.pdf");
    const { PdfDocumentAdapter, PdfJsAssetsUnavailableError } =
      await import("./pdf-document-adapter");

    await expect(PdfDocumentAdapter.open(getFreshUrl)).rejects.toBeInstanceOf(
      PdfJsAssetsUnavailableError,
    );
    expect(getFreshUrl).not.toHaveBeenCalled();
    expect(pdfjs.getDocument).not.toHaveBeenCalled();
  });
});

describe("bounded PDF search", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    pdfjs.getDocument.mockReset();
    mockAssetFetch();
  });

  async function openPages(texts: string[]) {
    const pages = texts.map((str) => ({
      cleanup: vi.fn(),
      streamTextContent: vi.fn(
        () =>
          new ReadableStream({
            start(controller) {
              controller.enqueue({ items: [{ str }] });
              controller.close();
            },
          }),
      ),
    }));
    const getPage = vi.fn(async (number: number) => pages[number - 1]);
    pdfjs.getDocument.mockReturnValue({
      destroy: vi.fn(),
      promise: Promise.resolve({ numPages: pages.length, getPage }),
    });
    const { PdfDocumentAdapter } = await import("./pdf-document-adapter");
    const adapter = await PdfDocumentAdapter.open(async () => "/fixture.pdf");
    return { adapter, getPage, pages };
  }

  it("bounds matches and reports truncation instead of claiming an exact count", async () => {
    const { adapter, getPage } = await openPages([
      "word ".repeat(2000),
      "word",
    ]);
    const result = await adapter.search("word");
    expect(result.matches).toHaveLength(1000);
    expect(result.limited).toBe(true);
    expect(getPage).toHaveBeenCalledTimes(1);
  });

  it("reuses text for repeated queries without retaining rendered resources", async () => {
    const { adapter, pages } = await openPages(["first query", "second query"]);
    expect((await adapter.search("query")).matches).toHaveLength(2);
    expect((await adapter.search("first")).matches).toHaveLength(1);
    for (const page of pages) {
      expect(page.streamTextContent).toHaveBeenCalledOnce();
      expect(page.cleanup).toHaveBeenCalledOnce();
    }
  });

  it("evicts pages beyond the finite text cache", async () => {
    const { adapter, pages } = await openPages(
      Array.from({ length: 9 }, () => "word"),
    );
    await adapter.search("word");
    await adapter.search("absent");
    expect(pages[0]!.streamTextContent).toHaveBeenCalledTimes(2);
  });

  it("cancels a live PDF worker text stream and never starts the next page", async () => {
    const cancel = vi.fn();
    const cleanup = vi.fn();
    let started!: () => void;
    const reading = new Promise<void>((resolve) => {
      started = resolve;
    });
    const getPage = vi.fn(async () => ({
      cleanup,
      streamTextContent: () =>
        new ReadableStream({
          pull() {
            started();
          },
          cancel,
        }),
    }));
    pdfjs.getDocument.mockReturnValue({
      destroy: vi.fn(),
      promise: Promise.resolve({ numPages: 50, getPage }),
    });
    const { PdfDocumentAdapter } = await import("./pdf-document-adapter");
    const adapter = await PdfDocumentAdapter.open(async () => "/fixture.pdf");
    const controller = new AbortController();
    const result = adapter.search("word", controller.signal);
    await reading;
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
    expect(cancel).toHaveBeenCalledOnce();
    expect(cleanup).toHaveBeenCalledOnce();
    expect(getPage).toHaveBeenCalledOnce();
  });
});

describe("PDF canvas disposal", () => {
  it("waits for render settlement and never clears a newer canvas owner", async () => {
    vi.resetModules();
    const { renderPdfPage } = await import("./pdf-document-adapter");
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      {} as CanvasRenderingContext2D,
    );
    pdfjs.TextLayer.mockImplementation(function () {
      return {
        render: async () => undefined,
        cancel: vi.fn(),
        textContentItemsStr: [],
        textDivs: [],
      };
    });
    const cleanup = vi.fn();
    const page = {
      cleanup,
      getViewport: () => ({ width: 600, height: 800, scale: 1 }),
      render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }),
      getTextContent: async () => ({ items: [] }),
      getAnnotations: async () => [],
    } as unknown as import("pdfjs-dist").PDFPageProxy;
    const canvas = document.createElement("canvas");
    const textLayer = document.createElement("div");
    const annotationLayer = document.createElement("div");
    const props = {
      page,
      canvas,
      textLayer,
      annotationLayer,
      annotationLinkClassName: "",
      annotationLinkLabel: "link",
      onInternalDestination: vi.fn(),
      scale: 1,
      searchMatches: [],
    };
    const first = renderPdfPage(props);
    await first.promise;
    const disposing = first.cancel();
    const second = renderPdfPage(props);
    await second.promise;
    expect(await disposing).toBe(false);
    expect(canvas.width).toBeGreaterThan(0);
    expect(cleanup).not.toHaveBeenCalled();
    textLayer.append(document.createTextNode("retained text"));
    expect(await second.cancel()).toBe(true);
    expect(canvas.width).toBe(0);
    expect(canvas.height).toBe(0);
    expect(textLayer.childNodes).toHaveLength(0);
    expect(cleanup).toHaveBeenCalledOnce();
  });
});
