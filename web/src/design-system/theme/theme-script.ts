import {
  colorSchemePreferences,
  defaultThemeName,
  themeNames,
} from "@/design-system/generated/theme-metadata";
import {
  colorSchemePreferenceKey,
  themePreferenceKey,
} from "./theme-preference";

export const themeInitializationScript = `
(() => {
  const root = document.documentElement;
  let cookies = {};
  try {
    cookies = Object.fromEntries(document.cookie.split("; ").filter(Boolean).map((entry) => {
      const separator = entry.indexOf("=");
      return separator < 0 ? [entry, ""] : [entry.slice(0, separator), entry.slice(separator + 1)];
    }));
  } catch {}
  let themeCandidate;
  let schemeCandidate;
  try {
    themeCandidate = localStorage.getItem(${JSON.stringify(themePreferenceKey)});
    schemeCandidate = localStorage.getItem(${JSON.stringify(colorSchemePreferenceKey)});
  } catch {}
  themeCandidate = themeCandidate || cookies[${JSON.stringify(themePreferenceKey)}];
  schemeCandidate = schemeCandidate || cookies[${JSON.stringify(colorSchemePreferenceKey)}];
  const storedTheme = ${JSON.stringify(themeNames)}.includes(themeCandidate)
    ? themeCandidate
    : ${JSON.stringify(defaultThemeName)};
  const storedScheme = ${JSON.stringify(colorSchemePreferences)}.includes(schemeCandidate)
    ? schemeCandidate
    : "system";
  const scheme = storedScheme === "system"
    ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : storedScheme;
  root.dataset.theme = storedTheme;
  root.dataset.colorScheme = scheme;
  root.style.colorScheme = scheme;
})();`;
