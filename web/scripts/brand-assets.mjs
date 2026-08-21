import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import sharp from "sharp";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, "..");
const masterPath = path.join(webRoot, "brand/source/scholens-raven-master.png");
const expectedMasterHash =
  "c0147099ca28a03f63e922b81177adb3e50667ca4da9370dc0ff3ed2558ef5de";

const mode = process.argv[2];
if (mode !== "build" && mode !== "check") {
  throw new Error("Usage: node scripts/brand-assets.mjs <build|check>");
}

const master = await readFile(masterPath);
const masterHash = createHash("sha256").update(master).digest("hex");
if (masterHash !== expectedMasterHash) {
  throw new Error(
    `Unexpected raven master hash: ${masterHash}. Review and record intentional source changes.`,
  );
}

const masterMetadata = await sharp(master).metadata();
if (masterMetadata.width !== 1254 || masterMetadata.height !== 1254) {
  throw new Error(
    `Raven master must remain 1254 × 1254; received ${masterMetadata.width} × ${masterMetadata.height}.`,
  );
}

const pngOptions = {
  compressionLevel: 9,
  effort: 10,
  palette: false,
};

function portrait(size) {
  return sharp(master)
    .resize(size, size, { fit: "cover" })
    .toColourspace("srgb")
    .png(pngOptions)
    .toBuffer();
}

function faviconFrame(size) {
  return sharp(master)
    .resize(size, size, { fit: "cover" })
    .toColourspace("srgb")
    .ensureAlpha()
    .png(pngOptions)
    .toBuffer();
}

function createIco(entries) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(entries.length, 4);

  const directory = Buffer.alloc(entries.length * 16);
  let offset = header.length + directory.length;
  entries.forEach(({ image, size }, index) => {
    const entryOffset = index * 16;
    directory.writeUInt8(size === 256 ? 0 : size, entryOffset);
    directory.writeUInt8(size === 256 ? 0 : size, entryOffset + 1);
    directory.writeUInt8(0, entryOffset + 2);
    directory.writeUInt8(0, entryOffset + 3);
    directory.writeUInt16LE(1, entryOffset + 4);
    directory.writeUInt16LE(32, entryOffset + 6);
    directory.writeUInt32LE(image.length, entryOffset + 8);
    directory.writeUInt32LE(offset, entryOffset + 12);
    offset += image.length;
  });

  return Buffer.concat([
    header,
    directory,
    ...entries.map(({ image }) => image),
  ]);
}

async function maskableIcon() {
  const insetPortrait = await portrait(410);
  return sharp({
    create: {
      width: 512,
      height: 512,
      channels: 4,
      background: "#000000",
    },
  })
    .composite([{ input: insetPortrait, left: 51, top: 51 }])
    .png(pngOptions)
    .toBuffer();
}

async function socialCard() {
  return sharp(master)
    .resize(1200, 630, { fit: "cover", position: "attention" })
    .toColourspace("srgb")
    .png(pngOptions)
    .toBuffer();
}

const faviconEntries = await Promise.all(
  [16, 32, 48].map(async (size) => ({
    image: await faviconFrame(size),
    size,
  })),
);
const portrait64 = await portrait(64);
const portrait128 = await portrait(128);
const portrait192 = await portrait(192);
const portrait256 = await portrait(256);
const portrait512 = await portrait(512);
const portrait1024 = await portrait(1024);
const shareImage = await socialCard();

const assets = new Map([
  ["src/app/favicon.ico", createIco(faviconEntries)],
  ["src/app/icon.png", portrait512],
  ["src/app/apple-icon.png", await portrait(180)],
  ["src/app/opengraph-image.png", shareImage],
  ["public/brand/scholens-raven-portrait-64.png", portrait64],
  ["public/brand/scholens-raven-portrait-128.png", portrait128],
  ["public/brand/icons/icon-192.png", portrait192],
  ["public/brand/icons/icon-512.png", portrait512],
  ["public/brand/icons/icon-maskable-512.png", await maskableIcon()],
  ["brand/exports/native/scholens-raven-64.png", portrait64],
  ["brand/exports/native/scholens-raven-128.png", portrait128],
  ["brand/exports/native/scholens-raven-256.png", portrait256],
  ["brand/exports/native/scholens-raven-512.png", portrait512],
  ["brand/exports/native/scholens-raven-1024.png", portrait1024],
]);

const rasterDimensions = new Map([
  ["src/app/icon.png", [512, 512]],
  ["src/app/apple-icon.png", [180, 180]],
  ["src/app/opengraph-image.png", [1200, 630]],
  ["public/brand/scholens-raven-portrait-64.png", [64, 64]],
  ["public/brand/scholens-raven-portrait-128.png", [128, 128]],
  ["public/brand/icons/icon-192.png", [192, 192]],
  ["public/brand/icons/icon-512.png", [512, 512]],
  ["public/brand/icons/icon-maskable-512.png", [512, 512]],
  ["brand/exports/native/scholens-raven-64.png", [64, 64]],
  ["brand/exports/native/scholens-raven-128.png", [128, 128]],
  ["brand/exports/native/scholens-raven-256.png", [256, 256]],
  ["brand/exports/native/scholens-raven-512.png", [512, 512]],
  ["brand/exports/native/scholens-raven-1024.png", [1024, 1024]],
]);

for (const [
  relativePath,
  [expectedWidth, expectedHeight],
] of rasterDimensions) {
  const generated = assets.get(relativePath);
  if (!generated) throw new Error(`Missing generated asset: ${relativePath}`);
  const metadata = await sharp(generated).metadata();
  if (metadata.width !== expectedWidth || metadata.height !== expectedHeight) {
    throw new Error(
      `${relativePath} must be ${expectedWidth} × ${expectedHeight}; received ${metadata.width} × ${metadata.height}.`,
    );
  }
}

const maskableStats = await sharp(
  assets.get("public/brand/icons/icon-maskable-512.png"),
).stats();
const maskableAlpha = maskableStats.channels[3];
if (maskableAlpha && maskableAlpha.min !== 255) {
  throw new Error("Maskable launcher artwork must be fully opaque.");
}

const failures = [];
for (const [relativePath, generated] of assets) {
  const destination = path.join(webRoot, relativePath);
  if (mode === "build") {
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(destination, generated);
    continue;
  }

  try {
    const committed = await readFile(destination);
    if (!committed.equals(generated)) failures.push(relativePath);
  } catch {
    failures.push(relativePath);
  }
}

if (failures.length > 0) {
  throw new Error(
    `Generated brand assets are stale or missing:\n${failures
      .map((file) => `- ${file}`)
      .join("\n")}\nRun pnpm brand:build and commit the results.`,
  );
}

process.stdout.write(
  mode === "build"
    ? `Generated ${assets.size} Scholens brand assets.\n`
    : `Verified ${assets.size} Scholens brand assets.\n`,
);
