import { beforeEach, describe, expect, it, vi } from "vitest";

const pdfjs = vi.hoisted(() => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: vi.fn(),
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
