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
    const featureFocusPattern =
      /focus(?:-visible)?:[^\s"'`]*(?:ring|border|shadow|outline-(?!none))/g;
    for (const match of contents.matchAll(featureFocusPattern)) {
      report(
        `${relativePath}:${lineNumber(contents, match.index)}: focus visuals belong to components/ui; consume keyboardFocusRing or a delegated text-control surface`,
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
