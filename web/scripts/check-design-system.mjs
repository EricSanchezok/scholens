import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import {
  flattenTokens,
  loadThemeContract,
  resolveTokenValue,
  tokenReference as reference,
} from "./theme-contract.mjs";

const webRoot = path.resolve(import.meta.dirname, "..");
const sourceRoot = path.join(webRoot, "src");
const tokenRoot = path.join(sourceRoot, "design-system", "tokens");
const generatedRoot = path.join(sourceRoot, "design-system", "generated");
const semanticIconRegistryPath = path.join(
  sourceRoot,
  "design-system",
  "icons",
  "semantic-icons.ts",
);

const readJson = async (filePath) =>
  JSON.parse(await readFile(filePath, "utf8"));

async function collectFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await collectFiles(entryPath)));
    else files.push(entryPath);
  }
  return files;
}

function lineNumber(contents, index) {
  return contents.slice(0, index).split("\n").length;
}

const violations = [];
const report = (message) => violations.push(message);

const semanticIconRegistrySource = await readFile(
  semanticIconRegistryPath,
  "utf8",
);
const semanticIconRegistryBody = semanticIconRegistrySource.match(
  /export const semanticIcons = \{([\s\S]*?)\} as const;/,
)?.[1];
if (!semanticIconRegistryBody) {
  report("src/design-system/icons/semantic-icons.ts: registry is missing");
} else {
  const mappings = [
    ...semanticIconRegistryBody.matchAll(/(\w+Icon):\s*"(\w+)"/g),
  ].map((match) => ({ semantic: match[1], glyph: match[2] }));
  const duplicateGlyphs = mappings.filter(
    ({ glyph }, index) =>
      mappings.findIndex((mapping) => mapping.glyph === glyph) !== index,
  );
  for (const { glyph, semantic } of duplicateGlyphs) {
    report(
      `src/design-system/icons/semantic-icons.ts: ${glyph} is registered for more than one semantic (including ${semantic})`,
    );
  }
  const exportedMappings = [
    ...semanticIconRegistrySource.matchAll(/(\w+)\s+as\s+(\w+Icon)/g),
  ].map((match) => ({ semantic: match[2], glyph: match[1] }));
  for (const mapping of mappings) {
    if (
      !exportedMappings.some(
        (candidate) =>
          candidate.semantic === mapping.semantic &&
          candidate.glyph === mapping.glyph,
      )
    ) {
      report(
        `src/design-system/icons/semantic-icons.ts: ${mapping.semantic} must export the registered ${mapping.glyph} glyph`,
      );
    }
  }
  for (const mapping of exportedMappings) {
    if (
      !mappings.some(
        (candidate) =>
          candidate.semantic === mapping.semantic &&
          candidate.glyph === mapping.glyph,
      )
    ) {
      report(
        `src/design-system/icons/semantic-icons.ts: ${mapping.semantic} export is missing from the semantic registry`,
      );
    }
  }
}

const themeContract = await loadThemeContract(tokenRoot);
const themeTokens = new Map(
  [...themeContract.themes].map(([name, theme]) => [
    name,
    flattenTokens(theme),
  ]),
);
const defaultThemeTokens = themeTokens.get(themeContract.defaultThemeName);
const dimensions = flattenTokens(
  await readJson(path.join(tokenRoot, "dimensions.json")),
);
const motion = flattenTokens(
  await readJson(path.join(tokenRoot, "motion.json")),
);
const light = flattenTokens(
  await readJson(path.join(tokenRoot, "semantic", "light.json")),
);
const dark = flattenTokens(
  await readJson(path.join(tokenRoot, "semantic", "dark.json")),
);

for (const [source, tokens] of [
  ["dimensions.json", dimensions],
  ["semantic/light.json", light],
  ["semantic/dark.json", dark],
  ...[...themeTokens].map(([name, tokens]) => [`themes/${name}.json`, tokens]),
]) {
  for (const retiredPath of ["color.focus.ring", "color.border.focus"]) {
    if (tokens.has(retiredPath)) {
      report(
        `src/design-system/tokens/${source}: retired ${retiredPath} token must not be restored`,
      );
    }
  }
}

const defaultThemePaths = [...defaultThemeTokens.keys()].sort();
const themeableTokenPaths = [
  /^primitive\./,
  /^palette\./,
  /^theme\.font\.interface$/,
  /^theme\.font\.weight\.(normal|medium|semibold)$/,
  /^theme\.radius\.(xs|sm|md|lg|xl|2xl)$/,
  /^theme\.icon\.stroke$/,
  /^elevation\./,
];
for (const tokenPath of defaultThemePaths) {
  if (!themeableTokenPaths.some((pattern) => pattern.test(tokenPath))) {
    report(
      `${tokenPath}: themes may express color, interface typography, non-pill radii, icon stroke, and elevation only`,
    );
  }
}
for (const [themeName, tokens] of themeTokens) {
  const paths = [...tokens.keys()].sort();
  for (const tokenPath of new Set([...defaultThemePaths, ...paths])) {
    const defaultToken = defaultThemeTokens.get(tokenPath);
    const token = tokens.get(tokenPath);
    if (!defaultToken || !token) {
      report(
        `${themeName}.${tokenPath}: theme token path must match ${themeContract.defaultThemeName}`,
      );
    } else if (defaultToken.$type !== token.$type) {
      report(
        `${themeName}.${tokenPath}: expected ${defaultToken.$type}, found ${token.$type}`,
      );
    }
  }

  for (const [tokenPath, token] of tokens) {
    if (!tokenPath.startsWith("palette.")) continue;
    const target = reference(token.$value);
    if (!target?.startsWith("primitive.")) {
      report(
        `${themeName}.${tokenPath}: theme palette values must reference primitive.* directly`,
      );
    } else if (!tokens.has(target)) {
      report(`${themeName}.${tokenPath}: unresolved reference ${target}`);
    }
  }
}

const lightPaths = [...light.keys()].sort();
const darkPaths = [...dark.keys()].sort();
for (const tokenPath of new Set([...lightPaths, ...darkPaths])) {
  const lightToken = light.get(tokenPath);
  const darkToken = dark.get(tokenPath);
  if (!lightToken || !darkToken) {
    report(`${tokenPath}: semantic token must exist in both Light and Dark`);
    continue;
  }
  if (lightToken.$type !== darkToken.$type) {
    report(`${tokenPath}: Light/Dark token types do not match`);
  }
  for (const [appearance, token] of [
    ["Light", lightToken],
    ["Dark", darkToken],
  ]) {
    const target = reference(token.$value);
    if (!target?.startsWith("palette.")) {
      report(`${tokenPath}: ${appearance} must reference palette.* directly`);
    } else {
      for (const [themeName, tokens] of themeTokens) {
        if (!tokens.has(target)) {
          report(
            `${themeName}.${tokenPath}: ${appearance} has unresolved reference ${target}`,
          );
        }
      }
    }
  }
}

const adapterPath = path.join(
  sourceRoot,
  "design-system",
  "adapters",
  "tailwind.json",
);
const adapter = await readJson(adapterPath);
const adapterNamespaces = {
  colors: "color",
  fontFamilies: "font",
  fontSizes: "text",
  fontWeights: "font-weight",
  radii: "radius",
  shadows: "shadow",
};
for (const [group, aliases] of Object.entries(adapter)) {
  for (const [name, target] of Object.entries(aliases)) {
    const valid =
      (light.has(target) && dark.has(target)) ||
      dimensions.has(target) ||
      defaultThemeTokens.has(target);
    if (!valid) report(`tailwind ${group}.${name}: unresolved token ${target}`);
    const namespace = adapterNamespaces[group];
    if (!namespace) {
      report(`tailwind ${group}: unknown adapter group`);
      continue;
    }
    if (`${namespace}-${name}` === target.replaceAll(".", "-")) {
      report(
        `tailwind ${group}.${name}: alias would create a self-referencing CSS variable`,
      );
    }
  }
}

for (const [themeName, tokens] of themeTokens) {
  for (const [tokenPath, token] of tokens) {
    if (!tokenPath.startsWith("elevation.")) continue;
    if (token.$type !== "shadow") {
      report(`${themeName}.${tokenPath}: expected DTCG shadow type`);
    }
    const colorTarget = reference(token.$value?.color);
    if (!colorTarget || !light.has(colorTarget) || !dark.has(colorTarget)) {
      report(
        `${themeName}.${tokenPath}: shadow color must resolve to a Light/Dark semantic token`,
      );
    }
  }
}

function rgba(hex) {
  if (typeof hex !== "string" || !/^#[0-9a-f]{6}(?:[0-9a-f]{2})?$/i.test(hex)) {
    return null;
  }
  const color = hex.slice(1);
  return {
    red: Number.parseInt(color.slice(0, 2), 16) / 255,
    green: Number.parseInt(color.slice(2, 4), 16) / 255,
    blue: Number.parseInt(color.slice(4, 6), 16) / 255,
    alpha:
      color.length === 8 ? Number.parseInt(color.slice(6, 8), 16) / 255 : 1,
  };
}

function composite(foreground, background) {
  return {
    red:
      foreground.red * foreground.alpha +
      background.red * (1 - foreground.alpha),
    green:
      foreground.green * foreground.alpha +
      background.green * (1 - foreground.alpha),
    blue:
      foreground.blue * foreground.alpha +
      background.blue * (1 - foreground.alpha),
    alpha: 1,
  };
}

function luminance(color) {
  const linear = [color.red, color.green, color.blue].map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

function contrastRatio(foregroundHex, backgroundHex) {
  const foreground = rgba(foregroundHex);
  const background = rgba(backgroundHex);
  if (!foreground || !background || background.alpha !== 1) return null;
  const resolvedForeground =
    foreground.alpha === 1 ? foreground : composite(foreground, background);
  const foregroundLuminance = luminance(resolvedForeground);
  const backgroundLuminance = luminance(background);
  return (
    (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
    (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
  );
}

const contrastContract = await readJson(path.join(tokenRoot, "contrast.json"));
for (const [themeName, tokens] of themeTokens) {
  for (const [appearanceName, appearanceTokens] of [
    ["light", light],
    ["dark", dark],
  ]) {
    const resolvedTokens = new Map([...tokens, ...appearanceTokens]);
    for (const { foreground, background, minimum } of contrastContract.pairs) {
      const foregroundValue = resolveTokenValue(resolvedTokens, foreground);
      const backgroundValue = resolveTokenValue(resolvedTokens, background);
      const ratio = contrastRatio(foregroundValue, backgroundValue);
      if (ratio === null) {
        report(
          `${themeName}/${appearanceName}: cannot resolve contrast pair ${foreground} on ${background}`,
        );
      } else if (ratio < minimum) {
        report(
          `${themeName}/${appearanceName}: ${foreground} on ${background} is ${ratio.toFixed(2)}:1, expected at least ${minimum}:1`,
        );
      }
    }
  }
}

const requiredCssMotionTokens = [
  "motion.duration.instant",
  "motion.duration.feedback",
  "motion.duration.fast",
  "motion.duration.standard",
  "motion.duration.slow",
  "motion.duration.deliberate",
  "motion.easing.enter",
  "motion.easing.standard",
  "motion.easing.exit",
  "motion.easing.in-out",
];
const requiredMotionTokens = [
  ...requiredCssMotionTokens,
  "motion.spring.layout.stiffness",
  "motion.spring.layout.damping",
  "motion.spring.layout.mass",
  "motion.spring.gentle.stiffness",
  "motion.spring.gentle.damping",
  "motion.spring.gentle.mass",
];
for (const tokenPath of requiredMotionTokens) {
  if (!motion.has(tokenPath))
    report(`${tokenPath}: required motion token missing`);
}
for (const [tokenPath, token] of motion) {
  const expectedType = tokenPath.startsWith("motion.duration.")
    ? "duration"
    : tokenPath.startsWith("motion.easing.")
      ? "cubicBezier"
      : "number";
  if (token.$type !== expectedType) {
    report(`${tokenPath}: expected ${expectedType}, found ${token.$type}`);
  }
  if (
    expectedType === "duration" &&
    (token.$value?.unit !== "ms" || token.$value?.value < 0)
  ) {
    report(`${tokenPath}: duration must be a non-negative millisecond value`);
  }
  if (
    expectedType === "cubicBezier" &&
    (!Array.isArray(token.$value) ||
      token.$value.length !== 4 ||
      token.$value.some((part) => typeof part !== "number"))
  ) {
    report(`${tokenPath}: cubicBezier must contain four numeric coordinates`);
  }
  if (
    expectedType === "number" &&
    (typeof token.$value !== "number" ||
      !Number.isFinite(token.$value) ||
      token.$value <= 0)
  ) {
    report(`${tokenPath}: spring parameters must be positive finite numbers`);
  }
}

const globalsPath = path.join(sourceRoot, "styles", "globals.css");
const globals = await readFile(globalsPath, "utf8");
const generatedFoundation = await readFile(
  path.join(generatedRoot, "dimensions.css"),
  "utf8",
);
const generatedMotion = await readFile(
  path.join(generatedRoot, "motion.css"),
  "utf8",
);
const motionConfig = await readFile(
  path.join(sourceRoot, "design-system", "motion", "motion-config.ts"),
  "utf8",
);
const motionRecipesPath = path.join(
  sourceRoot,
  "design-system",
  "motion",
  "motion-recipes.css",
);
const motionRecipes = await readFile(motionRecipesPath, "utf8");
if (generatedMotion.includes("--motion-spring-")) {
  report(
    "src/design-system/generated/motion.css: runtime-only spring parameters must not be exposed as CSS variables",
  );
}
for (const springName of ["layout", "gentle"]) {
  if (!motionConfig.includes(`...motionSprings.${springName}`)) {
    report(
      `src/design-system/motion/motion-config.ts: ${springName} must consume generated motionSprings metadata`,
    );
  }
}
for (const match of motionConfig.matchAll(
  /\b(?:stiffness|damping|mass)\s*:\s*\d/g,
)) {
  report(
    `src/design-system/motion/motion-config.ts:${lineNumber(motionConfig, match.index)}: spring numbers belong to motion.json`,
  );
}
const tailwindImportIndex = globals.indexOf('@import "tailwindcss";');
const foundationImportIndex = globals.indexOf(
  '@import "../design-system/generated/dimensions.css";',
);
if (
  foundationImportIndex === -1 ||
  tailwindImportIndex === -1 ||
  foundationImportIndex > tailwindImportIndex
) {
  report(
    "src/styles/globals.css: generated Tailwind theme aliases must be imported before tailwindcss so semantic utilities are emitted",
  );
}
if (!generatedFoundation.includes("@theme inline")) {
  report(
    "src/design-system/generated/dimensions.css: Tailwind adapter was not generated",
  );
}
for (const tokenPath of requiredCssMotionTokens) {
  const variable = `--${tokenPath.replaceAll(".", "-")}:`;
  if (!generatedMotion.includes(variable)) {
    report(`src/design-system/generated/motion.css: missing ${variable}`);
  }
}
for (const match of motionRecipes.matchAll(
  /transition(?:-property)?\s*:[^;}]*\b(?:width|height)\b/g,
)) {
  report(
    `src/design-system/motion/motion-recipes.css:${lineNumber(motionRecipes, match.index)}: layout dimensions must commit immediately; use bounded FLIP choreography`,
  );
}
for (const match of motionRecipes.matchAll(/\bwill-change\s*:/g)) {
  report(
    `src/design-system/motion/motion-recipes.css:${lineNumber(motionRecipes, match.index)}: persistent will-change is forbidden`,
  );
}
for (const [name, target] of Object.entries(adapter.fontSizes)) {
  const targetVariable = target.replaceAll(".", "-");
  const themeMapping = `--text-${name}: var(--${targetVariable});`;
  if (!generatedFoundation.includes(themeMapping)) {
    report(
      `src/design-system/generated/dimensions.css: text-${name} theme mapping was not generated`,
    );
  }
  const stableUtilityPattern = new RegExp(
    `@utility\\s+text-${name}\\s*\\{[^}]*font-size:\\s*var\\(--${targetVariable}\\);?[^}]*\\}`,
    "s",
  );
  if (!stableUtilityPattern.test(globals)) {
    report(
      `src/styles/globals.css: stable text-${name} utility must bind to --${targetVariable}`,
    );
  }
}
if (globals.includes("@theme")) {
  report(
    "src/styles/globals.css: @theme aliases are generated; do not maintain them here",
  );
}

const scanRoots = [sourceRoot, path.join(webRoot, ".storybook")];
const scannedFiles = (
  await Promise.all(scanRoots.map((root) => collectFiles(root)))
).flat();

const retiredFocusReferences = [
  {
    pattern: /\bkeyboardFocusRing\b/g,
    symbol: "keyboardFocusRing",
  },
  {
    pattern: /--color-focus-ring\b/g,
    symbol: "--color-focus-ring",
  },
  {
    pattern: /--color-border-focus\b/g,
    symbol: "--color-border-focus",
  },
  {
    pattern: /\bcolor\.focus\.ring\b/g,
    symbol: "color.focus.ring",
  },
  {
    pattern: /\bcolor\.border\.focus\b/g,
    symbol: "color.border.focus",
  },
];
for (const filePath of scannedFiles) {
  if (!new Set([".json", ".ts", ".tsx", ".css"]).has(path.extname(filePath))) {
    continue;
  }
  const contents = await readFile(filePath, "utf8");
  for (const { pattern, symbol } of retiredFocusReferences) {
    for (const match of contents.matchAll(pattern)) {
      report(
        `${path.relative(webRoot, filePath)}:${lineNumber(contents, match.index)}: retired focus contract ${symbol} must not be restored; consume focusSurfaceVariants({ intent })`,
      );
    }
  }
}

const excludedRoots = [generatedRoot, tokenRoot];
const motionRoot = path.join(sourceRoot, "design-system", "motion");
const runtimeFreeFeatureRoots = [
  "conversation",
  "home",
  "settings",
  "workspace-shell",
].map((feature) => path.join(sourceRoot, "features", feature));
const lightweightMotionImport = "@/design-system/motion/motion-provider";

function forbiddenMotionImports(contents) {
  const matches = contents.matchAll(
    /(?:from\s+|import\s*\(\s*|import\s+)["'](@\/design-system\/motion(?:\/[^"']*)?)["']/g,
  );
  return [...matches]
    .map((match) => match[1])
    .filter((specifier) => specifier !== lightweightMotionImport);
}

const motionBoundaryFixtures = [
  {
    source:
      'import { useMotionPreference } from "@/design-system/motion/motion-provider";',
    forbidden: [],
  },
  {
    source:
      'import type { ResolvedMotion } from "@/design-system/motion/motion-provider";',
    forbidden: [],
  },
  {
    source: 'import { m } from "@/design-system/motion";',
    forbidden: ["@/design-system/motion"],
  },
  {
    source:
      'import { MotionPresence } from "@/design-system/motion/motion-presence";',
    forbidden: ["@/design-system/motion/motion-presence"],
  },
  {
    source: 'import "@/design-system/motion/index";',
    forbidden: ["@/design-system/motion/index"],
  },
  {
    source:
      'const runtime = import("@/design-system/motion/motion-runtime-provider");',
    forbidden: ["@/design-system/motion/motion-runtime-provider"],
  },
];
for (const fixture of motionBoundaryFixtures) {
  const actual = forbiddenMotionImports(fixture.source);
  if (JSON.stringify(actual) !== JSON.stringify(fixture.forbidden)) {
    report(
      `scripts/check-design-system.mjs: runtime-free motion import self-test failed for ${fixture.source}`,
    );
  }
}

function splitTailwindSegments(token) {
  const segments = [];
  let current = "";
  let bracketDepth = 0;
  for (const character of token) {
    if (character === "[") bracketDepth += 1;
    if (character === "]") bracketDepth = Math.max(0, bracketDepth - 1);
    if (character === ":" && bracketDepth === 0) {
      segments.push(current);
      current = "";
    } else {
      current += character;
    }
  }
  segments.push(current);
  return segments;
}

function isTransientVariant(variant) {
  return (
    /(?:^|[-_:])(?:hover|focus(?:-visible|-within)?)(?:\/[\w-]+)?(?:\]|$)/.test(
      variant,
    ) || /:(?:hover|focus(?:-visible|-within)?)\b/.test(variant)
  );
}

function isPerimeterUtility(utility) {
  const normalized = utility.replace(/^[({]+|[)},;]+$/g, "");
  return (
    /^(?:-?border|ring|outline|shadow)(?:$|-)/.test(normalized) ||
    /^\[(?:box-shadow|border(?:-[\w-]+)?|outline(?:-[\w-]+)?):/.test(normalized)
  );
}

function transientPerimeterUtilities(contents) {
  const violations = [];
  for (const match of contents.matchAll(/[^\s"'`]+/g)) {
    const segments = splitTailwindSegments(match[0]);
    if (
      segments.length > 1 &&
      segments.slice(0, -1).some(isTransientVariant) &&
      isPerimeterUtility(segments.at(-1))
    ) {
      violations.push({ index: match.index, utility: match[0] });
    }
  }
  return violations;
}

const transientPerimeterFixtures = [
  ["hover:border-line-strong", true],
  ["focus:ring-1", true],
  ["focus-visible:outline-none", true],
  ["focus-within:shadow-raised", true],
  ["group-hover/item:border-control", true],
  ["peer-focus-visible:ring-2", true],
  ["lg:[&:focus-visible]:[box-shadow:0_0_0_1px_black]", true],
  ["hover:bg-hover focus-visible:text-foreground", false],
  ["aria-invalid:border-danger shadow-raised", false],
];
for (const [source, forbidden] of transientPerimeterFixtures) {
  if (transientPerimeterUtilities(source).length > 0 !== forbidden) {
    report(
      `scripts/check-design-system.mjs: transient perimeter self-test failed for ${source}`,
    );
  }
}

function maskForcedColorsBlocks(contents) {
  const ranges = [];
  for (const match of contents.matchAll(
    /@media\s*\(\s*forced-colors\s*:\s*active\s*\)/g,
  )) {
    const openingBrace = contents.indexOf("{", match.index);
    if (openingBrace === -1) continue;
    let depth = 0;
    let closingBrace = -1;
    for (let index = openingBrace; index < contents.length; index += 1) {
      if (contents[index] === "{") depth += 1;
      if (contents[index] === "}") depth -= 1;
      if (depth === 0) {
        closingBrace = index;
        break;
      }
    }
    if (closingBrace !== -1) ranges.push([match.index, closingBrace + 1]);
  }
  if (ranges.length === 0) return contents;
  const characters = [...contents];
  for (const [start, end] of ranges) {
    for (let index = start; index < end; index += 1) {
      if (characters[index] !== "\n") characters[index] = " ";
    }
  }
  return characters.join("");
}

function splitTopLevelSelectors(selectorList) {
  const selectors = [];
  let current = "";
  let escaped = false;
  let quote = null;
  let parenthesisDepth = 0;
  let bracketDepth = 0;
  for (const character of selectorList) {
    if (escaped) {
      current += character;
      escaped = false;
      continue;
    }
    if (character === "\\") {
      current += character;
      escaped = true;
      continue;
    }
    if (quote) {
      current += character;
      if (character === quote) quote = null;
      continue;
    }
    if (character === '"' || character === "'") {
      current += character;
      quote = character;
      continue;
    }
    if (character === "(") parenthesisDepth += 1;
    if (character === ")") {
      parenthesisDepth = Math.max(0, parenthesisDepth - 1);
    }
    if (character === "[") bracketDepth += 1;
    if (character === "]") bracketDepth = Math.max(0, bracketDepth - 1);
    if (character === "," && parenthesisDepth === 0 && bracketDepth === 0) {
      if (current.trim()) selectors.push(current.trim());
      current = "";
      continue;
    }
    current += character;
  }
  if (current.trim()) selectors.push(current.trim());
  return selectors;
}

function isAllowedSharedFocusDeclaration({
  property,
  relativePath,
  selector,
  value,
}) {
  if (
    relativePath === `src${path.sep}app${path.sep}global-error.tsx` &&
    selector === ".global-error-retry:focus-visible" &&
    property === "outline" &&
    value.trim() === "none"
  ) {
    return true;
  }
  if (relativePath !== `src${path.sep}styles${path.sep}globals.css`) {
    return false;
  }
  const sharedSelector =
    selector.includes(".focus-recipe") ||
    selector.includes("[data-focus-delegate]");
  if (sharedSelector && property === "outline" && value.trim() === "none") {
    return true;
  }
  if (sharedSelector && property === "outline-offset" && value.trim() === "0") {
    return true;
  }
  if (
    property === "box-shadow" &&
    value.trim() === "var(--shadow-raised)" &&
    /\.focus-recipe-(?:primary|danger|status)\b/.test(selector) &&
    !/\.focus-recipe-(?:neutral|selection|inline|scroll)\b/.test(selector)
  ) {
    return true;
  }
  return false;
}

function transientCssPerimeterDeclarations(contents, relativePath) {
  const unforced = maskForcedColorsBlocks(contents);
  const violations = [];
  for (const block of unforced.matchAll(/([^{}]+)\{([^{}]*)\}/gs)) {
    for (const selector of splitTopLevelSelectors(block[1])) {
      if (!/:(?:hover|focus(?:-visible|-within)?)\b/.test(selector)) continue;
      for (const declaration of block[2].matchAll(
        /\b(border(?:-[\w-]+)?|outline(?:-[\w-]+)?|box-shadow)\s*:\s*([^;}]+)/g,
      )) {
        const candidate = {
          property: declaration[1],
          relativePath,
          selector,
          value: declaration[2],
        };
        if (!isAllowedSharedFocusDeclaration(candidate)) {
          violations.push({
            index: block.index + block[0].indexOf(declaration[0]),
            ...candidate,
          });
        }
      }
    }
  }
  return violations;
}

function staticStyleBlocks(contents) {
  const blocks = [];
  const pattern =
    /<style(?:\s[^>]*)?>\s*\{\s*`([\s\S]*?)`\s*\}\s*<\/style\s*>/g;
  for (const match of contents.matchAll(pattern)) {
    if (match[1].includes("${")) continue;
    blocks.push({
      contents: match[1],
      index: match.index + match[0].indexOf("`") + 1,
    });
  }
  return blocks;
}

function staticStylePerimeterDeclarations(contents, relativePath) {
  return staticStyleBlocks(contents).flatMap((block) =>
    transientCssPerimeterDeclarations(block.contents, relativePath).map(
      (violation) => ({
        ...violation,
        index: block.index + violation.index,
      }),
    ),
  );
}

function jsxOpeningTags(contents) {
  const tags = [];
  for (let start = 0; start < contents.length; start += 1) {
    if (
      contents[start] !== "<" ||
      !/[A-Za-z]/.test(contents[start + 1] ?? "")
    ) {
      continue;
    }
    let braceDepth = 0;
    let escaped = false;
    let quote = null;
    for (let end = start + 1; end < contents.length; end += 1) {
      const character = contents[end];
      if (escaped) {
        escaped = false;
        continue;
      }
      if (character === "\\") {
        escaped = true;
        continue;
      }
      if (quote) {
        if (character === quote) quote = null;
        continue;
      }
      if (character === '"' || character === "'" || character === "`") {
        quote = character;
        continue;
      }
      if (character === "{") braceDepth += 1;
      if (character === "}") braceDepth = Math.max(0, braceDepth - 1);
      if (character === ">" && braceDepth === 0) {
        tags.push({ contents: contents.slice(start, end + 1), index: start });
        start = end;
        break;
      }
    }
  }
  return tags;
}

function focusDelegationViolations(contents) {
  const surfaceDelegatePattern = /\bdata-focus-delegate\s*=\s*["']surface["']/;
  const surfaceOwnerPattern = /\bdata-focus-surface(?:\s|=|\/>|>)/;
  const neutralRecipePattern =
    /focusSurfaceVariants\s*\(\s*\{\s*intent\s*:\s*["']neutral["']\s*,?\s*\}\s*\)/;
  const tags = jsxOpeningTags(contents);
  const delegates = tags.filter((tag) =>
    surfaceDelegatePattern.test(tag.contents),
  );
  const owners = tags.filter((tag) => surfaceOwnerPattern.test(tag.contents));
  const violations = owners
    .filter((owner) => !neutralRecipePattern.test(owner.contents))
    .map((owner) => ({
      index: owner.index,
      message:
        'data-focus-surface owners must consume focusSurfaceVariants({ intent: "neutral" }) on the same element',
    }));

  if (delegates.length > owners.length) {
    for (const delegate of delegates.slice(owners.length)) {
      violations.push({
        index: delegate.index,
        message:
          'data-focus-delegate="surface" requires a paired data-focus-surface owner',
      });
    }
  } else if (owners.length > delegates.length) {
    for (const owner of owners.slice(delegates.length)) {
      violations.push({
        index: owner.index,
        message:
          'data-focus-surface requires a paired data-focus-delegate="surface" child',
      });
    }
  }
  return violations;
}

const transientCssFixtures = [
  [".field:hover { border-color: currentColor; }", "fixture.css", true],
  [
    ".group:focus-within .child { box-shadow: 0 0 0 1px currentColor; }",
    "fixture.css",
    true,
  ],
  [".field:focus-visible { outline: none; }", "fixture.css", true],
  [
    "@media (forced-colors: active) { .field:focus-visible { outline: 2px solid Highlight; } }",
    "fixture.css",
    false,
  ],
  [
    ".focus-recipe-primary:focus-visible { box-shadow: var(--shadow-raised); }",
    `src${path.sep}styles${path.sep}globals.css`,
    false,
  ],
  [
    ".focus-recipe-neutral:focus-visible { box-shadow: var(--shadow-raised); }",
    `src${path.sep}styles${path.sep}globals.css`,
    true,
  ],
  [
    ".focus-recipe:focus-visible, .field:focus-visible { outline: none; }",
    `src${path.sep}styles${path.sep}globals.css`,
    true,
  ],
  [
    ":is(.focus-recipe-primary:focus-visible, .focus-recipe-danger:focus-visible) { box-shadow: var(--shadow-raised); }",
    `src${path.sep}styles${path.sep}globals.css`,
    false,
  ],
  [
    ".focus-recipe-primary:focus-visible, .field:focus-visible { box-shadow: var(--shadow-raised); }",
    `src${path.sep}styles${path.sep}globals.css`,
    true,
  ],
  [".field:hover { background: Canvas; }", "fixture.css", false],
];
for (const [source, relativePath, forbidden] of transientCssFixtures) {
  if (
    transientCssPerimeterDeclarations(source, relativePath).length > 0 !==
    forbidden
  ) {
    report(
      `scripts/check-design-system.mjs: transient CSS perimeter self-test failed for ${source}`,
    );
  }
}

const staticStyleFixtures = [
  {
    forbidden: 1,
    relativePath: `src${path.sep}features${path.sep}fixture.tsx`,
    source: "<style>{`.field:focus-visible { outline: none; }`}</style>",
  },
  {
    forbidden: 0,
    relativePath: `src${path.sep}features${path.sep}fixture.tsx`,
    source:
      "<style>{`@media (forced-colors: active) { .field:focus-visible { outline: 2px solid Highlight; } }`}</style>",
  },
  {
    forbidden: 0,
    relativePath: `src${path.sep}app${path.sep}global-error.tsx`,
    source:
      "<style>{`.global-error-retry:focus-visible { outline: none; } @media (forced-colors: active) { .global-error-retry:focus-visible { outline: 2px solid Highlight; } }`}</style>",
  },
  {
    forbidden: 1,
    relativePath: `src${path.sep}app${path.sep}global-error.tsx`,
    source: "<style>{`.global-error-retry:hover { outline: none; }`}</style>",
  },
];
for (const { forbidden, relativePath, source } of staticStyleFixtures) {
  if (
    staticStylePerimeterDeclarations(source, relativePath).length !== forbidden
  ) {
    report(
      `scripts/check-design-system.mjs: static style focus self-test failed for ${source}`,
    );
  }
}

const focusDelegationFixtures = [
  {
    source:
      '<div className={focusSurfaceVariants({ intent: "neutral" })} data-focus-surface><input data-focus-delegate="surface" /></div>',
    violations: 0,
  },
  {
    source: '<input data-focus-delegate="surface" />',
    violations: 1,
  },
  {
    source:
      '<div className={focusSurfaceVariants({ intent: "neutral" })} data-focus-surface />',
    violations: 1,
  },
  {
    source:
      '<div className="bg-surface" data-focus-surface><input data-focus-delegate="surface" /></div>',
    violations: 1,
  },
  {
    source:
      'expect(field).toHaveAttribute("data-focus-delegate", "surface"); expect(owner).toHaveAttribute("data-focus-surface");',
    violations: 0,
  },
];
for (const { source, violations: expected } of focusDelegationFixtures) {
  if (focusDelegationViolations(source).length !== expected) {
    report(
      `scripts/check-design-system.mjs: focus delegation self-test failed for ${source}`,
    );
  }
}

const checks = [
  {
    pattern:
      /#[0-9a-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\s*\(|\b(?:hwb|lab|lch|oklab|oklch)\s*\(/g,
    message: "raw color found outside token sources",
  },
  {
    pattern: /\bdark:/g,
    message: "dark: variant bypasses semantic appearance tokens",
  },
  {
    pattern: /!important/g,
    message: "!important is forbidden in product styling",
  },
  {
    pattern: /var\(--(?:primitive|palette)-/g,
    message:
      "primitive/palette CSS variables may not be consumed by components",
  },
  {
    pattern: /color-mix\(in_srgb/g,
    message: "use a perceptual color-mix space such as in_oklab",
  },
  {
    pattern: /text-\[(?:11|13)px\]/g,
    message: "use the text-caption or text-ui typography token",
  },
];

for (const filePath of scannedFiles) {
  if (
    excludedRoots.some(
      (root) => filePath === root || filePath.startsWith(`${root}${path.sep}`),
    ) ||
    !new Set([".ts", ".tsx", ".css"]).has(path.extname(filePath))
  ) {
    continue;
  }
  const contents = await readFile(filePath, "utf8");
  const relativePath = path.relative(webRoot, filePath);
  if (
    !filePath.startsWith(`${motionRoot}${path.sep}`) &&
    /from\s+["']motion\//.test(contents)
  ) {
    report(
      `${relativePath}: import Motion through src/design-system/motion only`,
    );
  }
  const runtimeFreeBoundary =
    filePath === path.join(sourceRoot, "app", "providers.tsx") ||
    runtimeFreeFeatureRoots.some(
      (root) => filePath === root || filePath.startsWith(`${root}${path.sep}`),
    );
  if (runtimeFreeBoundary) {
    for (const specifier of forbiddenMotionImports(contents)) {
      report(
        `${relativePath}: this initial-route boundary may import only ${lightweightMotionImport}; forbidden ${specifier}`,
      );
    }
  }
  if (!filePath.startsWith(`${motionRoot}${path.sep}`)) {
    const motionChecks = [
      {
        pattern: /\btransition-all\b/g,
        message: "transition-all is forbidden; use a semantic motion recipe",
      },
      {
        pattern: /\b(?:duration|ease|animate|transition)-(?!none\b)[^\s"'`]+/g,
        message: "raw motion utility found; use a semantic motion recipe",
      },
      {
        pattern: /@keyframes\s+/g,
        message: "keyframes belong to src/design-system/motion",
      },
      {
        pattern: /\bcubic-bezier\s*\(|\b\d+(?:\.\d+)?ms\b/g,
        message: "raw timing value found outside the motion foundation",
      },
    ];
    for (const { pattern, message } of motionChecks) {
      for (const match of contents.matchAll(pattern)) {
        report(
          `${relativePath}:${lineNumber(contents, match.index)}: ${message}`,
        );
      }
    }
  }
  if (
    relativePath.startsWith(`src${path.sep}features${path.sep}`) ||
    relativePath.startsWith(`src${path.sep}app${path.sep}`)
  ) {
    if (/from\s+["']iconoir-react["']/.test(contents)) {
      report(
        `${relativePath}: product code must import a semantic icon from src/design-system/icons/semantic-icons.ts`,
      );
    }
  }
  if (new Set([".ts", ".tsx"]).has(path.extname(filePath))) {
    for (const match of transientPerimeterUtilities(contents)) {
      report(
        `${relativePath}:${lineNumber(contents, match.index)}: transient border/ring/outline/shadow utility ${match.utility} is forbidden; consume focusSurfaceVariants({ intent }) so the perimeter remains stable`,
      );
    }
  }
  if (path.extname(filePath) === ".tsx") {
    for (const match of staticStylePerimeterDeclarations(
      contents,
      relativePath,
    )) {
      report(
        `${relativePath}:${lineNumber(contents, match.index)}: ${match.property} in static style focus selector ${match.selector} is forbidden outside the exact global-error fallback or forced-colors override`,
      );
    }
    for (const violation of focusDelegationViolations(contents)) {
      report(
        `${relativePath}:${lineNumber(contents, violation.index)}: ${violation.message}`,
      );
    }
  }
  if (path.extname(filePath) === ".css") {
    for (const match of transientCssPerimeterDeclarations(
      contents,
      relativePath,
    )) {
      report(
        `${relativePath}:${lineNumber(contents, match.index)}: ${match.property} in transient selector ${match.selector} is forbidden outside the shared focus recipe or forced-colors override`,
      );
    }
  }
  for (const { pattern, message } of checks) {
    for (const match of contents.matchAll(pattern)) {
      report(
        `${path.relative(webRoot, filePath)}:${lineNumber(contents, match.index)}: ${message}`,
      );
    }
  }
}

const preview = await readFile(
  path.join(webRoot, ".storybook", "preview.tsx"),
  "utf8",
);
const generatedThemesCss = await readFile(
  path.join(generatedRoot, "themes.css"),
  "utf8",
);
for (const themeName of themeContract.themeNames) {
  if (!generatedThemesCss.includes(`[data-theme="${themeName}"] {`)) {
    report(`generated/themes.css: missing ${themeName} theme selector`);
  }
  for (const appearance of ["light", "dark"]) {
    if (
      !generatedThemesCss.includes(
        `[data-theme="${themeName}"][data-color-scheme="${appearance}"] {`,
      )
    ) {
      report(
        `generated/themes.css: missing ${themeName}/${appearance} selector`,
      );
    }
  }
}
for (const globalName of [
  "theme",
  "appearance",
  "motion",
  "locale",
  "network",
  "data",
]) {
  if (!preview.includes(`${globalName}: {`)) {
    report(`.storybook/preview.tsx: missing ${globalName} global control`);
  }
}
if (!preview.includes("context.globals.theme")) {
  report(".storybook/preview.tsx: Theme toolbar must drive the active theme");
}
if (!preview.includes("items: themeNames.map")) {
  report(".storybook/preview.tsx: Theme toolbar must use generated themeNames");
}
if (!preview.includes('a11y: { test: "error" }')) {
  report(
    ".storybook/preview.tsx: accessibility checks must fail on violations",
  );
}

const featureRoot = path.join(sourceRoot, "features");
const featureEntries = await readdir(featureRoot, { withFileTypes: true });
for (const entry of featureEntries.filter((item) => item.isDirectory())) {
  const files = await collectFiles(path.join(featureRoot, entry.name));
  if (!files.some((file) => file.endsWith(".stories.tsx"))) {
    report(
      `src/features/${entry.name}: implemented feature has no Storybook state catalog`,
    );
  }
}

if (violations.length > 0) {
  console.error("Design-system contract violations:\n");
  console.error(violations.map((violation) => `- ${violation}`).join("\n"));
  process.exit(1);
}

const storyCount = scannedFiles.filter((file) =>
  file.endsWith(".stories.tsx"),
).length;
const themeLabel = themeContract.themeNames.length === 1 ? "theme" : "themes";
console.log(
  `Design-system contract is clean (${themeContract.themeNames.length} ${themeLabel}, ${light.size} semantic tokens per appearance, ${storyCount} story files).`,
);
