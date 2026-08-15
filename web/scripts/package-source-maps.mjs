import { createHash } from "node:crypto";
import {
  cp,
  mkdir,
  readFile,
  readdir,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";

const releaseSha = process.env.NEXT_PUBLIC_RELEASE_SHA;
if (!/^[0-9a-f]{40}$/.test(releaseSha ?? "")) {
  throw new Error("NEXT_PUBLIC_RELEASE_SHA must be a lowercase commit SHA");
}

const sourceRoot = path.resolve(".next");
const outputRoot = "/tmp/scholens-source-maps";
await rm(outputRoot, { recursive: true, force: true });

async function sourceMapPaths(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const discovered = [];
  for (const entry of entries) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      discovered.push(...(await sourceMapPaths(absolute)));
    } else if (entry.isFile() && entry.name.endsWith(".map")) {
      discovered.push(absolute);
    }
  }
  return discovered;
}

const maps = (await sourceMapPaths(sourceRoot)).sort();
if (maps.length === 0) {
  throw new Error("the production build produced no source maps");
}

const files = [];
const aggregate = createHash("sha256");
for (const source of maps) {
  const relative = path.relative(sourceRoot, source).split(path.sep).join("/");
  const destination = path.join(outputRoot, relative);
  const contents = await readFile(source);
  const checksum = createHash("sha256").update(contents).digest("hex");
  const metadata = await stat(source);
  await mkdir(path.dirname(destination), { recursive: true });
  await cp(source, destination, { force: false, errorOnExist: true });
  files.push({ path: relative, sha256: checksum, size: metadata.size });
  aggregate.update(relative);
  aggregate.update("\0");
  aggregate.update(checksum);
  aggregate.update("\0");
  aggregate.update(String(metadata.size));
  aggregate.update("\n");
}

const index = {
  aggregate_sha256: aggregate.digest("hex"),
  contract_version: 1,
  files,
  release_sha: releaseSha,
};
await writeFile(
  `${outputRoot}/index.json`,
  `${JSON.stringify(index, null, 2)}\n`,
);
