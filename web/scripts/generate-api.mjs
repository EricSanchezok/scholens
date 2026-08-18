#!/usr/bin/env node
// Regenerates the web API types from the committed public OpenAPI snapshot.
//
// Codegen-only transform: openapi-typescript's default `defaultNonNullable`
// behavior turns any property with a `default` into a required (non-optional)
// type. The published contract intentionally keeps `add_to_library` defaulting
// to true, but the web production code must not be forced to send it. This
// script strips only those two request properties' `default` from the input
// handed to the generator, so the emitted types mark them optional while the
// committed snapshot and server behavior stay unchanged.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputPath = process.argv[2];
if (!outputPath) {
  throw new Error("Usage: node scripts/generate-api.mjs <output>");
}

const source = path.join(root, "..", "server", "openapi", "public-v1.json");
const doc = JSON.parse(fs.readFileSync(source, "utf8"));

const pointers = [
  "/components/schemas/PaperIngestionRequest/properties/add_to_library",
  "/components/schemas/PreparePaperUploadRequest/properties/add_to_library",
];
for (const pointer of pointers) {
  const node = pointer
    .split("/")
    .slice(1)
    .reduce((acc, part) => acc?.[part], doc);
  if (!node || typeof node !== "object") {
    throw new Error(`Codegen transform target not found: ${pointer}`);
  }
  delete node.default;
}

const temporaryDirectory = fs.mkdtempSync(
  path.join(os.tmpdir(), "scholens-api-transform-"),
);
const transformedPath = path.join(temporaryDirectory, "openapi.json");
fs.writeFileSync(transformedPath, JSON.stringify(doc));
try {
  execFileSync(
    "pnpm",
    ["exec", "openapi-typescript", transformedPath, "-o", outputPath],
    { cwd: root, stdio: "inherit" },
  );
} finally {
  fs.rmSync(temporaryDirectory, { recursive: true, force: true });
}
