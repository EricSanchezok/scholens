import { readFile } from "node:fs/promises";
import path from "node:path";

const repositoryRoot = path.resolve(import.meta.dirname, "..", "..");
const contractPath = path.join(
  repositoryRoot,
  "server",
  "contracts",
  "mcp-v1.json",
);
const documentationFactsPath = path.join(
  repositoryRoot,
  "web",
  "src",
  "features",
  "documentation",
  "documentation-content.ts",
);

const contract = JSON.parse(await readFile(contractPath, "utf8"));
const documentationFacts = await readFile(documentationFactsPath, "utf8");
const declaredToolCount = documentationFacts.match(
  /export const MCP_TOOL_COUNT = (\d+);/,
)?.[1];
const capabilityStart = documentationFacts.indexOf(
  "export const mcpCapabilityGroups = [",
);
const capabilityEnd = documentationFacts.indexOf(
  "] as const;",
  capabilityStart,
);

if (declaredToolCount === undefined) {
  throw new Error("Documentation facts must declare a numeric MCP_TOOL_COUNT");
}
if (capabilityStart < 0 || capabilityEnd < 0) {
  throw new Error("Documentation facts must declare mcpCapabilityGroups");
}
if (
  contract.endpoint !== "/mcp" ||
  contract.tools === null ||
  Array.isArray(contract.tools) ||
  typeof contract.tools !== "object"
) {
  throw new Error("server/contracts/mcp-v1.json is not an MCP v1 snapshot");
}

const capabilitySource = documentationFacts.slice(
  capabilityStart,
  capabilityEnd,
);
const capabilityCounts = [...capabilitySource.matchAll(/count: (\d+),/g)].map(
  (match) => Number(match[1]),
);
const pageToolCount = Number(declaredToolCount);
const groupedToolCount = capabilityCounts.reduce(
  (total, count) => total + count,
  0,
);
const contractToolCount = Object.keys(contract.tools).length;

if (capabilityCounts.length !== 6) {
  throw new Error(
    `Documentation must retain six capability groups; found ${capabilityCounts.length}`,
  );
}
if (pageToolCount !== groupedToolCount || pageToolCount !== contractToolCount) {
  throw new Error(
    [
      "MCP documentation count drift detected:",
      `page=${pageToolCount}`,
      `groups=${groupedToolCount}`,
      `contract=${contractToolCount}`,
    ].join(" "),
  );
}

console.log(
  `MCP documentation contract is aligned (${contractToolCount} snapshot tools, six capability groups).`,
);
