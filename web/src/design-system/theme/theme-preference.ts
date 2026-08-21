import {
  colorSchemePreferences,
  defaultThemeName,
  themeNames,
  type ColorSchemePreference,
  type ThemeName,
} from "@/design-system/generated/theme-metadata";

export const themePreferenceKey = "scholens-theme";
export const colorSchemePreferenceKey = "scholens-color-scheme";

export function parseThemeName(value: string | null | undefined): ThemeName {
  return themeNames.includes(value as ThemeName)
    ? (value as ThemeName)
    : defaultThemeName;
}

export function parseColorSchemePreference(
  value: string | null | undefined,
): ColorSchemePreference {
  return colorSchemePreferences.includes(value as ColorSchemePreference)
    ? (value as ColorSchemePreference)
    : "system";
}

function cookieValue(name: string) {
  if (typeof document === "undefined") return undefined;
  const prefix = `${name}=`;
  try {
    return document.cookie
      .split("; ")
      .find((entry) => entry.startsWith(prefix))
      ?.slice(prefix.length);
  } catch {
    return undefined;
  }
}

function storedValue(key: string) {
  if (typeof window === "undefined") return undefined;
  try {
    return localStorage.getItem(key) ?? cookieValue(key);
  } catch {
    return cookieValue(key);
  }
}

export function storedTheme(): ThemeName {
  return parseThemeName(storedValue(themePreferenceKey));
}

export function storedColorSchemePreference(): ColorSchemePreference {
  return parseColorSchemePreference(storedValue(colorSchemePreferenceKey));
}

export function persistPreference(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {}
  try {
    document.cookie = `${key}=${value}; path=/; max-age=31536000; samesite=lax`;
  } catch {}
}
