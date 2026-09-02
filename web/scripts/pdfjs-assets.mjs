import { createHash } from "node:crypto";
import {
  cp,
  mkdir,
  readFile,
  readdir,
  realpath,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, "..");
const sourcePackageEntry = path.resolve(
  webRoot,
  "node_modules/pdfjs-dist/build/pdf.mjs",
);
const sourceWasmDirectory = path.resolve(
  path.dirname(sourcePackageEntry),
  "..",
  "wasm",
);
const destinationRoot = path.join(webRoot, "public", "pdfjs", "wasm");
const mode = process.argv[2];

if (mode !== "build" && mode !== "check") {
  throw new Error("Usage: node scripts/pdfjs-assets.mjs <build|check>");
}

const release = process.env.NEXT_PUBLIC_RELEASE_SHA ?? "development";
if (!/^[A-Za-z0-9._-]+$/.test(release)) {
  throw new Error(
    `Invalid NEXT_PUBLIC_RELEASE_SHA for a static path: ${release}`,
  );
}

const destinationDirectory = path.join(destinationRoot, release);
const manifestPath = path.join(destinationDirectory, "manifest.json");
const requiredWasmFiles = new Set([
  "jbig2.wasm",
  "openjpeg.wasm",
  "qcms_bg.wasm",
]);
const requiredFallbackFiles = new Set([
  "jbig2_nowasm_fallback.js",
  "openjpeg_nowasm_fallback.js",
]);

async function ensureSource() {
  const sourceDirectory = await realpath(sourceWasmDirectory).catch(() => {
    throw new Error(
      `pdfjs-dist WASM directory is missing: ${sourceWasmDirectory}. Run pnpm install --frozen-lockfile.`,
    );
  });
  const sourceEntries = await readdir(sourceDirectory, { withFileTypes: true });
  const files = sourceEntries
    .filter((entry) => entry.isFile())
    .map((entry) => entry.name)
    .sort();
  for (const required of [...requiredWasmFiles, ...requiredFallbackFiles]) {
    if (!files.includes(required)) {
      throw new Error(
        `pdfjs-dist is missing required codec asset: ${required}`,
      );
    }
  }
  return { files, sourceDirectory };
}

async function readPdfjsVersion() {
  const packageJsonPath = path.resolve(sourceWasmDirectory, "../package.json");
  const packageJson = JSON.parse(await readFile(packageJsonPath, "utf8"));
  if (typeof packageJson.version !== "string" || !packageJson.version) {
    throw new Error("pdfjs-dist package.json does not declare a version");
  }
  return packageJson.version;
}

async function fileDigest(filePath) {
  const contents = await readFile(filePath);
  return {
    sha256: createHash("sha256").update(contents).digest("hex"),
    size: contents.byteLength,
  };
}

async function createManifest(files, sourceDirectory, pdfjsVersion) {
  const entries = {};
  for (const file of files) {
    const filePath = path.join(sourceDirectory, file);
    const fileStat = await stat(filePath);
    if (!fileStat.isFile()) continue;
    entries[file] = await fileDigest(filePath);
  }
  return {
    files: entries,
    pdfjs_version: pdfjsVersion,
    release,
    schema: 1,
  };
}

async function assertWasmHeaders(directory) {
  for (const required of requiredWasmFiles) {
    const contents = await readFile(path.join(directory, required));
    if (
      contents.length < 4 ||
      !contents.subarray(0, 4).equals(Buffer.from([0, 97, 115, 109]))
    ) {
      throw new Error(`${required} is not a valid WebAssembly binary`);
    }
  }
}

const { files, sourceDirectory } = await ensureSource();
const pdfjsVersion = await readPdfjsVersion();
const manifest = await createManifest(files, sourceDirectory, pdfjsVersion);

if (mode === "build") {
  await rm(destinationRoot, { force: true, recursive: true });
  await mkdir(destinationDirectory, { recursive: true });
  await cp(sourceDirectory, destinationDirectory, { recursive: true });
  await assertWasmHeaders(destinationDirectory);
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  process.stdout.write(
    `Generated ${files.length} PDF.js assets for ${release} (${pdfjsVersion}).\n`,
  );
} else {
  const generatedManifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (JSON.stringify(generatedManifest) !== JSON.stringify(manifest)) {
    throw new Error(
      `PDF.js assets are stale for ${release}. Run pnpm pdfjs:assets.`,
    );
  }
  await assertWasmHeaders(destinationDirectory);
  for (const file of files) {
    const expected = manifest.files[file];
    const actual = await fileDigest(path.join(destinationDirectory, file));
    if (actual.size !== expected.size || actual.sha256 !== expected.sha256) {
      throw new Error(`PDF.js asset is stale or missing: ${file}`);
    }
  }
  process.stdout.write(
    `Verified ${files.length} PDF.js assets for ${release} (${pdfjsVersion}).\n`,
  );
}
