"use client";

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

import {
  type ColorScheme,
  type ColorSchemePreference,
  defaultThemeName,
  type ThemeName,
} from "@/design-system/generated/theme-metadata";
import {
  colorSchemePreferenceKey,
  persistPreference,
  storedColorSchemePreference,
  storedTheme,
  themePreferenceKey,
} from "./theme-preference";

type ThemeContextValue = {
  ready: boolean;
  theme: ThemeName;
  colorScheme: ColorScheme;
  colorSchemePreference: ColorSchemePreference;
  setTheme: (theme: ThemeName) => void;
  setColorSchemePreference: (preference: ColorSchemePreference) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);
const subscribeToHydration = () => () => {};

function subscribeToSystemScheme(onStoreChange: () => void) {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", onStoreChange);
  return () => media.removeEventListener("change", onStoreChange);
}

export function ThemeProvider({
  children,
  initialTheme,
  initialColorSchemePreference,
}: Readonly<{
  children: React.ReactNode;
  initialTheme?: ThemeName;
  initialColorSchemePreference?: ColorSchemePreference;
}>) {
  const parent = useContext(ThemeContext);

  if (parent) return children;

  return (
    <ThemeProviderRoot
      initialColorSchemePreference={initialColorSchemePreference}
      initialTheme={initialTheme}
    >
      {children}
    </ThemeProviderRoot>
  );
}

function ThemeProviderRoot({
  children,
  initialTheme,
  initialColorSchemePreference,
}: Readonly<{
  children: React.ReactNode;
  initialTheme?: ThemeName;
  initialColorSchemePreference?: ColorSchemePreference;
}>) {
  const ready = useSyncExternalStore(
    subscribeToHydration,
    () => true,
    () => false,
  );
  const [persistedTheme, setThemeState] = useState<ThemeName>(
    initialTheme ?? storedTheme,
  );
  const [persistedColorSchemePreference, setColorSchemePreferenceState] =
    useState<ColorSchemePreference>(
      initialColorSchemePreference ?? storedColorSchemePreference,
    );
  // Keep the server and first hydration render identical. The inline script
  // owns the root attributes before paint; React adopts persisted state once
  // useSyncExternalStore reports that hydration has completed.
  const hydrationTheme = initialTheme ?? defaultThemeName;
  const hydrationColorSchemePreference =
    initialColorSchemePreference ?? "system";
  const theme = ready ? persistedTheme : hydrationTheme;
  const colorSchemePreference = ready
    ? persistedColorSchemePreference
    : hydrationColorSchemePreference;
  const systemIsDark = useSyncExternalStore(
    subscribeToSystemScheme,
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
    () => false,
  );
  const colorScheme: ColorScheme =
    colorSchemePreference === "system"
      ? systemIsDark
        ? "dark"
        : "light"
      : colorSchemePreference;

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.colorScheme = colorScheme;
    root.style.colorScheme = colorScheme;
  }, [colorScheme, theme]);

  const setTheme = useCallback((nextTheme: ThemeName) => {
    setThemeState(nextTheme);
    persistPreference(themePreferenceKey, nextTheme);
  }, []);

  const setColorSchemePreference = useCallback(
    (nextPreference: ColorSchemePreference) => {
      setColorSchemePreferenceState(nextPreference);
      persistPreference(colorSchemePreferenceKey, nextPreference);
    },
    [],
  );

  const value = useMemo(
    () => ({
      ready,
      theme,
      colorScheme,
      colorSchemePreference,
      setTheme,
      setColorSchemePreference,
    }),
    [
      ready,
      theme,
      colorScheme,
      colorSchemePreference,
      setTheme,
      setColorSchemePreference,
    ],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
