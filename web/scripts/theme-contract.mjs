import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

export const appearanceNames = ["light", "dark"];

const themeIdPattern = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;

export function flattenTokens(value, prefix = [], tokens = new Map()) {
  for (const [name, child] of Object.entries(value)) {
    const tokenPath = [...prefix, name];
    if (child && typeof child === "object" && "$value" in child) {
      tokens.set(tokenPath.join("."), child);
    } else if (child && typeof child === "object") {
      flattenTokens(child, tokenPath, tokens);
    }
  }
  return tokens;
}

export function tokenReference(value) {
  return typeof value === "string" ? value.match(/^\{([^}]+)\}$/)?.[1] : null;
}

export function resolveTokenValue(tokens, tokenPath, seen = new Set()) {
  if (seen.has(tokenPath)) return undefined;
  seen.add(tokenPath);
  const value = tokens.get(tokenPath)?.$value;
  const target = tokenReference(value);
  return target ? resolveTokenValue(tokens, target, seen) : value;
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

export async function loadThemeContract(tokenDirectory) {
  const themeDirectory = path.join(tokenDirectory, "themes");
  const manifestPath = path.join(themeDirectory, "manifest.json");
  const manifest = await readJson(manifestPath);
  const violations = [];

  if (manifest.version !== 1) {
    violations.push("themes/manifest.json: version must be 1");
  }
  if (!Array.isArray(manifest.themes) || manifest.themes.length === 0) {
    violations.push("themes/manifest.json: themes must be a non-empty array");
  }

  const themeNames = Array.isArray(manifest.themes) ? manifest.themes : [];
  const uniqueThemeNames = new Set(themeNames);
  if (uniqueThemeNames.size !== themeNames.length) {
    violations.push("themes/manifest.json: theme ids must be unique");
  }
  for (const themeName of themeNames) {
    if (typeof themeName !== "string" || !themeIdPattern.test(themeName)) {
      violations.push(
        `themes/manifest.json: invalid kebab-case theme id ${JSON.stringify(themeName)}`,
      );
    }
  }
  if (!uniqueThemeNames.has(manifest.defaultTheme)) {
    violations.push(
      "themes/manifest.json: defaultTheme must name a registered theme",
    );
  }

  const registeredFiles = new Set(themeNames.map((name) => `${name}.json`));
  const themeFiles = (await readdir(themeDirectory))
    .filter((name) => name.endsWith(".json") && name !== "manifest.json")
    .sort();
  for (const fileName of themeFiles) {
    if (!registeredFiles.has(fileName)) {
      violations.push(`themes/${fileName}: theme file is not registered`);
    }
  }
  for (const fileName of registeredFiles) {
    if (!themeFiles.includes(fileName)) {
      violations.push(`themes/${fileName}: registered theme file is missing`);
    }
  }

  const themes = new Map();
  for (const themeName of themeNames) {
    const themePath = path.join(themeDirectory, `${themeName}.json`);
    if (themeFiles.includes(`${themeName}.json`)) {
      themes.set(themeName, await readJson(themePath));
    }
  }

  if (violations.length > 0) {
    throw new Error(violations.join("\n"));
  }

  return {
    defaultThemeName: manifest.defaultTheme,
    themeNames,
    themes,
  };
}
