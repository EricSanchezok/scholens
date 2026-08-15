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
import { LazyMotion, MotionConfig } from "motion/react";

export const motionPreferences = ["system", "reduced", "full"] as const;
export type MotionPreference = (typeof motionPreferences)[number];
export type ResolvedMotion = Exclude<MotionPreference, "system">;

type MotionContextValue = {
  ready: boolean;
  preference: MotionPreference;
  resolved: ResolvedMotion;
  setPreference: (preference: MotionPreference) => void;
};

const MotionContext = createContext<MotionContextValue | null>(null);
const loadMotionFeatures = () =>
  import("./motion-features").then((module) => module.default);
const subscribeToHydration = () => () => {};

export function parseMotionPreference(
  value: string | null | undefined,
): MotionPreference {
  return motionPreferences.includes(value as MotionPreference)
    ? (value as MotionPreference)
    : "system";
}

function cookieValue(name: string) {
  if (typeof document === "undefined") return undefined;
  const prefix = `${name}=`;
  return document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(prefix))
    ?.slice(prefix.length);
}

export function storedMotionPreference(): MotionPreference {
  if (typeof window === "undefined") return "system";
  let stored: string | null = null;
  try {
    stored = localStorage.getItem("scholens-motion");
  } catch {}
  return parseMotionPreference(stored ?? cookieValue("scholens-motion"));
}

function subscribeToReducedMotion(onStoreChange: () => void) {
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  media.addEventListener("change", onStoreChange);
  return () => media.removeEventListener("change", onStoreChange);
}

export function MotionProvider({
  children,
  initialPreference,
  skipAnimations = false,
}: Readonly<{
  children: React.ReactNode;
  initialPreference?: MotionPreference;
  skipAnimations?: boolean;
}>) {
  const parent = useContext(MotionContext);

  if (parent) return children;

  return (
    <MotionProviderRoot
      initialPreference={initialPreference}
      skipAnimations={skipAnimations}
    >
      {children}
    </MotionProviderRoot>
  );
}

function MotionProviderRoot({
  children,
  initialPreference,
  skipAnimations,
}: Readonly<{
  children: React.ReactNode;
  initialPreference?: MotionPreference;
  skipAnimations: boolean;
}>) {
  const ready = useSyncExternalStore(
    subscribeToHydration,
    () => true,
    () => false,
  );
  const [preference, setPreferenceState] = useState<MotionPreference>(
    initialPreference ?? storedMotionPreference,
  );
  const systemReduced = useSyncExternalStore(
    subscribeToReducedMotion,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
  const resolved: ResolvedMotion =
    preference === "system" ? (systemReduced ? "reduced" : "full") : preference;

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.motionPreference = preference;
    root.dataset.motion = resolved;
  }, [preference, resolved]);

  const setPreference = useCallback((nextPreference: MotionPreference) => {
    setPreferenceState(nextPreference);
    try {
      localStorage.setItem("scholens-motion", nextPreference);
    } catch {}
    try {
      document.cookie = `scholens-motion=${nextPreference}; path=/; max-age=31536000; samesite=lax`;
    } catch {}
  }, []);

  const value = useMemo(
    () => ({ ready, preference, resolved, setPreference }),
    [ready, preference, resolved, setPreference],
  );

  return (
    <MotionContext.Provider value={value}>
      <MotionConfig
        reducedMotion={
          preference === "system"
            ? "user"
            : resolved === "reduced"
              ? "always"
              : "never"
        }
        skipAnimations={skipAnimations}
      >
        <LazyMotion features={loadMotionFeatures} strict>
          {children}
        </LazyMotion>
      </MotionConfig>
    </MotionContext.Provider>
  );
}

export function useMotionPreference() {
  const context = useContext(MotionContext);
  if (!context) {
    throw new Error("useMotionPreference must be used within MotionProvider");
  }
  return context;
}
