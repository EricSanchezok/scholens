import { access, readFile, readdir } from "node:fs/promises";
import { execFile } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { promisify } from "node:util";

const repositoryRoot = path.resolve(import.meta.dirname, "..", "..");
const webRoot = path.join(repositoryRoot, "web");
const documentationRoots = [
  path.join(repositoryRoot, "AGENTS.md"),
  path.join(repositoryRoot, "CONTRIBUTING.md"),
  path.join(repositoryRoot, "DEVELOPMENT.md"),
  path.join(repositoryRoot, "PRODUCT.md"),
  path.join(repositoryRoot, "README.md"),
  path.join(repositoryRoot, "README.zh-CN.md"),
  path.join(repositoryRoot, "NOTICE.md"),
  path.join(repositoryRoot, "docs"),
  path.join(repositoryRoot, "packages"),
  path.join(repositoryRoot, "server", "README.md"),
  path.join(repositoryRoot, "jobs", "README.md"),
  path.join(repositoryRoot, "client", "README.md"),
  path.join(repositoryRoot, "client", "src", "content", "legal"),
  path.join(repositoryRoot, "deploy", "ecs"),
  path.join(webRoot, "README.md"),
  path.join(webRoot, "docs"),
];
const markdownLinkPattern = /!?(?:\[[^\]]*\])\(([^)]+)\)/g;
const ignoredDocumentationDirectories = new Set([
  ".git",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
  ".venv",
  "__pycache__",
  "node_modules",
]);

async function collectMarkdown(target) {
  const entries = await readdir(target, { withFileTypes: true }).catch(
    () => undefined,
  );
  if (!entries) return [target];
  const files = [];
  for (const entry of entries) {
    const entryPath = path.join(target, entry.name);
    if (
      entry.isDirectory() &&
      !ignoredDocumentationDirectories.has(entry.name)
    ) {
      files.push(...(await collectMarkdown(entryPath)));
    } else if (/\.mdx?$/.test(entry.name)) files.push(entryPath);
  }
  return files;
}

function display(filePath) {
  return path.relative(repositoryRoot, filePath);
}

const files = (
  await Promise.all(documentationRoots.map((target) => collectMarkdown(target)))
).flat();
const violations = [];

const execFileAsync = promisify(execFile);
const { stdout: listedFiles } = await execFileAsync(
  "git",
  ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
  { cwd: repositoryRoot, encoding: "utf8", maxBuffer: 10 * 1024 * 1024 },
);
const repositoryFiles = listedFiles.split("\0").filter(Boolean);

const allowedProvenanceFiles = new Set([
  "NOTICE.md",
  "web/scripts/check-docs.mjs",
]);
const forbiddenProvenancePatterns = [
  { label: "joined upstream brand", pattern: /\bOpenPaper\b/i },
  { label: "spaced upstream brand", pattern: /\bOpen Paper\b/ },
  { label: "upstream organization brand", pattern: /\bKhoj\b/i },
  {
    label: "upstream repository URL",
    pattern: /github\.com\/khoj-ai\/openpaper/i,
  },
  { label: "upstream asset domain", pattern: /assets\.khoj\.dev/i },
];
const skippedTextExtensions = new Set([
  ".avif",
  ".gif",
  ".ico",
  ".jpeg",
  ".jpg",
  ".lock",
  ".mov",
  ".mp4",
  ".pdf",
  ".png",
  ".webm",
  ".webp",
  ".woff",
  ".woff2",
]);

for (const repositoryFile of repositoryFiles) {
  if (allowedProvenanceFiles.has(repositoryFile)) continue;
  const fileName = path.basename(repositoryFile);
  if (
    skippedTextExtensions.has(path.extname(repositoryFile).toLowerCase()) ||
    fileName.endsWith(".lock")
  ) {
    continue;
  }
  const filePath = path.join(repositoryRoot, repositoryFile);
  const contents = await readFile(filePath, "utf8").catch(() => undefined);
  if (contents === undefined || contents.includes("\0")) continue;
  for (const { label, pattern } of forbiddenProvenancePatterns) {
    if (pattern.test(repositoryFile) || pattern.test(contents)) {
      violations.push(`${repositoryFile}: forbidden ${label} reference`);
    }
  }
}

const mediaExtensions = new Set([
  ".avif",
  ".gif",
  ".ico",
  ".jpeg",
  ".jpg",
  ".mov",
  ".mp4",
  ".png",
  ".svg",
  ".webm",
  ".webp",
]);
const mediaManifestPath = path.join(
  repositoryRoot,
  "docs",
  "media-assets.json",
);
const mediaManifest = JSON.parse(await readFile(mediaManifestPath, "utf8"));
if (mediaManifest.version !== 1 || !Array.isArray(mediaManifest.assets)) {
  violations.push(
    "docs/media-assets.json: expected version 1 and an assets array",
  );
}
const registeredMedia = new Map();
for (const asset of mediaManifest.assets ?? []) {
  if (
    typeof asset?.path !== "string" ||
    typeof asset?.source !== "string" ||
    typeof asset?.license !== "string" ||
    typeof asset?.purpose !== "string" ||
    typeof asset?.verifiedVersion !== "string"
  ) {
    violations.push(
      "docs/media-assets.json: every asset needs path, source, license, purpose, and verifiedVersion",
    );
    continue;
  }
  registeredMedia.set(asset.path, asset);
}
const repositoryMedia = repositoryFiles.filter((file) =>
  mediaExtensions.has(path.extname(file).toLowerCase()),
);
for (const mediaPath of repositoryMedia) {
  if (!registeredMedia.has(mediaPath)) {
    violations.push(`${mediaPath}: media asset is not registered`);
  }
}
for (const mediaPath of registeredMedia.keys()) {
  if (!repositoryMedia.includes(mediaPath)) {
    violations.push(
      `docs/media-assets.json: missing registered asset ${mediaPath}`,
    );
  }
}

for (const filePath of files) {
  const contents = await readFile(filePath, "utf8");
  if (
    /!\[[^\]]*\]\(\s*<?https?:\/\//i.test(contents) ||
    /<(?:img|source|video)\b[^>]*\bsrc=["']https?:\/\//i.test(contents)
  ) {
    violations.push(`${display(filePath)}: remote media is not registered`);
  }
  for (const match of contents.matchAll(markdownLinkPattern)) {
    const rawTarget = match[1]?.trim();
    if (
      !rawTarget ||
      rawTarget.startsWith("#") ||
      /^[a-z][a-z0-9+.-]*:/i.test(rawTarget)
    ) {
      continue;
    }
    const withoutTitle = rawTarget.match(
      /^<?([^ >]+)>?(?:\s+["'][^"']*["'])?$/,
    )?.[1];
    if (!withoutTitle) continue;
    const decodedTarget = decodeURIComponent(withoutTitle.split("#")[0] ?? "");
    if (!decodedTarget) continue;
    const resolved = path.resolve(path.dirname(filePath), decodedTarget);
    try {
      await access(resolved);
    } catch {
      violations.push(`${display(filePath)}: broken local link ${rawTarget}`);
    }
  }
}

const packageJson = JSON.parse(
  await readFile(path.join(webRoot, "package.json"), "utf8"),
);
const expectedScripts = {
  dev: "next dev --hostname 127.0.0.1 --port 7300",
  "design:check": "node scripts/check-design-system.mjs",
  start: "next start --hostname 127.0.0.1 --port 7300",
  storybook: "storybook dev -p 7306 --host 127.0.0.1 --exact-port --no-open",
};
for (const [name, expected] of Object.entries(expectedScripts)) {
  if (packageJson.scripts?.[name] !== expected) {
    violations.push(
      `web/package.json: ${name} must remain ${JSON.stringify(expected)}`,
    );
  }
}

const activePortDocs = [
  path.join(repositoryRoot, "AGENTS.md"),
  path.join(repositoryRoot, "DEVELOPMENT.md"),
  path.join(webRoot, "README.md"),
];
for (const filePath of activePortDocs) {
  const contents = await readFile(filePath, "utf8");
  if (/localhost:300[0136]|127\.0\.0\.1:300[0136]/.test(contents)) {
    violations.push(
      `${display(filePath)}: stale pre-contract frontend port found`,
    );
  }
}

const decisionsDirectory = path.join(repositoryRoot, "docs", "decisions");
const decisionFiles = (await readdir(decisionsDirectory))
  .filter((name) => /^\d{4}-.+\.md$/.test(name))
  .sort();
const decisionIndex = await readFile(
  path.join(decisionsDirectory, "README.md"),
  "utf8",
);
for (const decisionFile of decisionFiles) {
  if (!decisionIndex.includes(`./${decisionFile}`)) {
    violations.push(`docs/decisions/README.md: missing ${decisionFile}`);
  }
  const decisionContents = await readFile(
    path.join(decisionsDirectory, decisionFile),
    "utf8",
  );
  for (const heading of [
    "## Problem",
    "## Decision",
    "## Alternatives considered",
    "## Consequences",
  ]) {
    if (!decisionContents.includes(heading)) {
      violations.push(`docs/decisions/${decisionFile}: missing ${heading}`);
    }
  }
}

if (violations.length > 0) {
  console.error("Documentation contract violations:\n");
  console.error(violations.map((violation) => `- ${violation}`).join("\n"));
  process.exit(1);
}

console.log(
  `Documentation contract is clean (${files.length} Markdown/MDX files checked).`,
);
