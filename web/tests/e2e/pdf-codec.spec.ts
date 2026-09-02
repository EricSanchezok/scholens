import { expect, test } from "@playwright/test";

const requiredCodecAssets = [
  { contentType: "application/wasm", file: "jbig2.wasm" },
  { contentType: "application/wasm", file: "openjpeg.wasm" },
  { contentType: "application/wasm", file: "qcms_bg.wasm" },
  {
    contentType: "javascript",
    file: "jbig2_nowasm_fallback.js",
  },
  {
    contentType: "javascript",
    file: "openjpeg_nowasm_fallback.js",
  },
] as const;

test("publishes PDF.js codec assets from the production build", async ({
  request,
}) => {
  const manifestResponse = await request.get(
    "/pdfjs/wasm/development/manifest.json",
  );
  expect(manifestResponse.status()).toBe(200);
  expect(manifestResponse.headers()["content-type"]).toContain(
    "application/json",
  );
  const manifest = (await manifestResponse.json()) as {
    files: Record<string, unknown>;
    pdfjs_version: string;
    release: string;
    schema: number;
  };
  expect(manifest).toMatchObject({
    release: "development",
    schema: 1,
  });
  expect(manifest.pdfjs_version).toMatch(/^\d+\.\d+\.\d+$/);

  for (const { contentType, file } of requiredCodecAssets) {
    expect(manifest.files[file]).toBeDefined();
    const head = await request.head(`/pdfjs/wasm/development/${file}`);
    expect(head.status()).toBe(200);
    expect(head.headers()["content-type"]).toContain(contentType);

    const response = await request.get(`/pdfjs/wasm/development/${file}`);
    expect(response.status()).toBe(200);
    if (file.endsWith(".wasm")) {
      expect((await response.body()).subarray(0, 4)).toEqual(
        Buffer.from([0, 97, 115, 109]),
      );
    }
  }
});
