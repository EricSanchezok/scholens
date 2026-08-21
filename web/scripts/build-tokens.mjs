import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import prettier from "prettier";
import StyleDictionary from "style-dictionary";

import {
  appearanceNames,
  flattenTokens,
  loadThemeContract,
  resolveTokenValue,
} from "./theme-contract.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = process.env.SCHOLENS_TOKEN_OUTPUT_DIR
  ? path.resolve(process.env.SCHOLENS_TOKEN_OUTPUT_DIR)
  : path.join(root, "src/design-system/generated");
const tokenDirectory = path.join(root, "src/design-system/tokens");
const adapterDirectory = path.join(root, "src/design-system/adapters");
const themeContract = await loadThemeContract(tokenDirectory);

const formatValue = (value) => {
  if (
    Array.isArray(value) &&
    value.length === 4 &&
    value.every((part) => typeof part === "number")
  ) {
    return `cubic-bezier(${value.join(", ")})`;
  }
  if (
    typeof value === "object" &&
    value &&
    "color" in value &&
    "offsetX" in value &&
    "offsetY" in value &&
    "blur" in value &&
    "spread" in value
  ) {
    return [value.offsetX, value.offsetY, value.blur, value.spread, value.color]
      .map(formatValue)
      .join(" ");
  }
  if (
    typeof value === "object" &&
    value &&
    "value" in value &&
    "unit" in value
  ) {
    return `${value.value}${value.unit}`;
  }
  return String(value);
};

StyleDictionary.registerFormat({
  name: "scholens/css-variables",
  format: ({ dictionary, options }) => {
    const lines = dictionary.allTokens
      .filter((token) => {
        const tokenPath = token.path.join(".");
        return (
          options.prefixes.includes(token.path[0]) &&
          !options.excludedPrefixes?.some(
            (prefix) =>
              tokenPath === prefix || tokenPath.startsWith(`${prefix}.`),
          )
        );
      })
      .map(
        (token) =>
          `  --${token.path.join("-")}: ${formatValue(token.$value ?? token.value)};`,
      )
      .sort();

    return `${options.selector} {\n${lines.join("\n")}\n}\n`;
  },
});

const build = async ({
  name,
  sources,
  tokens,
  selector,
  prefixes,
  excludedPrefixes = [],
}) => {
  const dictionary = new StyleDictionary({
    ...(sources
      ? { source: sources.map((source) => path.join(tokenDirectory, source)) }
      : {}),
    ...(tokens ? { tokens } : {}),
    platforms: {
      css: {
        transformGroup: "css",
        buildPath: `${outputDirectory}/`,
        files: [
          {
            destination: `${name}.css`,
            format: "scholens/css-variables",
            options: { selector, prefixes, excludedPrefixes },
          },
        ],
      },
    },
  });

  await dictionary.buildAllPlatforms();
};

await fs.mkdir(outputDirectory, { recursive: true });

await build({
  name: "dimensions",
  sources: ["dimensions.json"],
  selector: ":root",
  prefixes: [
    "space",
    "radius",
    "layout",
    "control",
    "icon",
    "touch",
    "border",
    "focus",
    "type",
    "font",
    "opacity",
    "scrollbar",
  ],
});

await build({
  name: "motion",
  sources: ["motion.json"],
  selector: ":root",
  prefixes: ["motion"],
  excludedPrefixes: ["motion.spring"],
});

const themePartNames = [];
for (const themeName of themeContract.themeNames) {
  const themePartName = `theme-${themeName}`;
  themePartNames.push(themePartName);
  await build({
    name: themePartName,
    tokens: { theme: themeContract.themes.get(themeName).theme },
    selector: `[data-theme=\"${themeName}\"]`,
    prefixes: ["theme"],
  });

  for (const appearance of appearanceNames) {
    const appearancePartName = `theme-${themeName}-${appearance}`;
    themePartNames.push(appearancePartName);
    await build({
      name: appearancePartName,
      sources: [`themes/${themeName}.json`, `semantic/${appearance}.json`],
      selector: `[data-theme=\"${themeName}\"][data-color-scheme=\"${appearance}\"]`,
      prefixes: ["color", "elevation"],
    });
  }
}

const themeCss = (
  await Promise.all(
    themePartNames.map((name) =>
      fs.readFile(path.join(outputDirectory, `${name}.css`), "utf8"),
    ),
  )
).join("\n");
await fs.writeFile(
  path.join(outputDirectory, "themes.css"),
  await prettier.format(themeCss, { parser: "css" }),
  "utf8",
);
await Promise.all(
  themePartNames.map((name) =>
    fs.rm(path.join(outputDirectory, `${name}.css`), { force: true }),
  ),
);
await Promise.all(
  ["colors-light.css", "colors-dark.css"].map((name) =>
    fs.rm(path.join(outputDirectory, name), { force: true }),
  ),
);

for (const output of ["dimensions.css", "motion.css"]) {
  const outputPath = path.join(outputDirectory, output);
  const source = await fs.readFile(outputPath, "utf8");
  await fs.writeFile(
    outputPath,
    await prettier.format(source, { parser: "css" }),
    "utf8",
  );
}

const pwaColorPaths = {
  canvas: "color.bg.canvas",
  textPrimary: "color.text.primary",
  textSecondary: "color.text.secondary",
  borderDefault: "color.border.default",
};
const pwaColors = {};
const defaultThemeTokens = flattenTokens(
  themeContract.themes.get(themeContract.defaultThemeName),
);
for (const appearance of appearanceNames) {
  const semanticTokens = flattenTokens(
    JSON.parse(
      await fs.readFile(
        path.join(tokenDirectory, `semantic/${appearance}.json`),
        "utf8",
      ),
    ),
  );
  const resolvedTokens = new Map([...defaultThemeTokens, ...semanticTokens]);
  pwaColors[appearance] = Object.fromEntries(
    Object.entries(pwaColorPaths).map(([name, tokenPath]) => {
      const value = resolveTokenValue(resolvedTokens, tokenPath);
      if (typeof value !== "string") {
        throw new Error(
          `Cannot resolve PWA color ${appearance}.${name} from ${tokenPath}`,
        );
      }
      return [name, value];
    }),
  );
}

const metadata =
  `// Generated by scripts/build-tokens.mjs. Do not edit.\n` +
  `export const defaultThemeName = ${JSON.stringify(themeContract.defaultThemeName)} as const;\n` +
  `export const themeNames = ${JSON.stringify(themeContract.themeNames)} as const;\n` +
  `export const colorSchemes = ${JSON.stringify(appearanceNames)} as const;\n` +
  `export const colorSchemePreferences = [\"system\", ...colorSchemes] as const;\n` +
  `export const pwaColors = ${JSON.stringify(pwaColors, null, 2)} as const;\n\n` +
  `export type ThemeName = (typeof themeNames)[number];\n` +
  `export type ColorScheme = (typeof colorSchemes)[number];\n` +
  `export type ColorSchemePreference = (typeof colorSchemePreferences)[number];\n`;

await fs.writeFile(
  path.join(outputDirectory, "theme-metadata.ts"),
  await prettier.format(metadata, { parser: "typescript" }),
  "utf8",
);

const primitiveColors = JSON.parse(
  await fs.readFile(path.join(tokenDirectory, "primitives.json"), "utf8"),
).primitive;
const colorMetadata =
  `// Generated by scripts/build-tokens.mjs. Do not edit.\n` +
  `export const metadataColors = ${JSON.stringify(
    {
      brandInk: primitiveColors.neutral["950"].$value,
      canvasDark: primitiveColors.neutral["1000"].$value,
      canvasLight: primitiveColors.neutral["0"].$value,
      launcherBackground: primitiveColors.neutral["50"].$value,
    },
    null,
    2,
  )} as const;\n`;
await fs.writeFile(
  path.join(outputDirectory, "color-metadata.ts"),
  await prettier.format(colorMetadata, { parser: "typescript" }),
  "utf8",
);

const motionSource = JSON.parse(
  await fs.readFile(path.join(tokenDirectory, "motion.json"), "utf8"),
).motion;
const motionDurations = Object.fromEntries(
  Object.entries(motionSource.duration).map(([name, token]) => [
    name.replaceAll("-", "_"),
    token.$value.value,
  ]),
);
const motionEasings = Object.fromEntries(
  Object.entries(motionSource.easing).map(([name, token]) => [
    name.replaceAll("-", "_"),
    token.$value,
  ]),
);
const motionCssEasings = Object.fromEntries(
  Object.entries(motionEasings).map(([name, values]) => [
    name,
    `cubic-bezier(${values.join(", ")})`,
  ]),
);
const motionSprings = Object.fromEntries(
  Object.entries(motionSource.spring).map(([name, spring]) => [
    name.replaceAll("-", "_"),
    Object.fromEntries(
      Object.entries(spring).map(([property, token]) => [
        property.replaceAll("-", "_"),
        token.$value,
      ]),
    ),
  ]),
);
const motionMetadata =
  `// Generated by scripts/build-tokens.mjs. Do not edit.\n` +
  `export const motionDurations = ${JSON.stringify(motionDurations, null, 2)} as const;\n` +
  `export const motionEasings = ${JSON.stringify(motionEasings, null, 2)} as const;\n` +
  `export const motionCssEasings = ${JSON.stringify(motionCssEasings, null, 2)} as const;\n\n` +
  `export const motionSprings = ${JSON.stringify(motionSprings, null, 2)} as const;\n\n` +
  `export type MotionDurationName = keyof typeof motionDurations;\n` +
  `export type MotionEasingName = keyof typeof motionEasings;\n` +
  `export type MotionSpringName = keyof typeof motionSprings;\n`;
await fs.writeFile(
  path.join(outputDirectory, "motion-metadata.ts"),
  await prettier.format(motionMetadata, { parser: "typescript" }),
  "utf8",
);

const tailwindAliases = JSON.parse(
  await fs.readFile(path.join(adapterDirectory, "tailwind.json"), "utf8"),
);
const tailwindLines = [
  ...Object.entries(tailwindAliases.colors).map(
    ([name, token]) =>
      `  --color-${name}: var(--${token.replaceAll(".", "-")});`,
  ),
  ...Object.entries(tailwindAliases.fontSizes).map(
    ([name, token]) =>
      `  --text-${name}: var(--${token.replaceAll(".", "-")});`,
  ),
  ...Object.entries(tailwindAliases.fontFamilies).map(
    ([name, token]) =>
      `  --font-${name}: var(--${token.replaceAll(".", "-")});`,
  ),
  ...Object.entries(tailwindAliases.fontWeights).map(
    ([name, token]) =>
      `  --font-weight-${name}: var(--${token.replaceAll(".", "-")});`,
  ),
  ...Object.entries(tailwindAliases.radii).map(
    ([name, token]) =>
      `  --radius-${name}: var(--${token.replaceAll(".", "-")});`,
  ),
  ...Object.entries(tailwindAliases.shadows).map(
    ([name, token]) =>
      `  --shadow-${name}: var(--${token.replaceAll(".", "-")});`,
  ),
].sort();
await fs.appendFile(
  path.join(outputDirectory, "dimensions.css"),
  `@theme inline {\n${tailwindLines.join("\n")}\n}\n`,
);
