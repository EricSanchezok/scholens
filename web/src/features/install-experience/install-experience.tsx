"use client";

import * as React from "react";

import { isStandaloneDisplayMode } from "@/lib/browser/display-mode";
import {
  detectInstallEnvironment,
  resolveInstallStatus,
  type InstallEnvironment,
  type InstallExperienceStatus,
  type InstallInstructionKind,
} from "./install-environment";

export const installStorageKeys = {
  firstLaunch: "scholens:pwa-first-launch:v1",
  promotion: "scholens:pwa-install-promotion:v1",
} as const;

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

type InstallExperienceValue = {
  completeFirstLaunch: () => void;
  dismissPromotion: () => void;
  firstLaunchHintVisible: boolean;
  instructionKind?: InstallInstructionKind;
  instructionsOpen: boolean;
  markPromotionShown: () => void;
  openInstallExperience: () => Promise<void>;
  promotionVisible: boolean;
  recordCoreAction: () => void;
  setInstructionsOpen: (open: boolean) => void;
  showInstallEntry: boolean;
  status: InstallExperienceStatus;
};

const InstallExperienceContext = React.createContext<
  InstallExperienceValue | undefined
>(undefined);

function readFlag(key: string) {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string) {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // Private browsing and locked-down WebViews may deny persistent storage.
  }
}

function browserEnvironment(): InstallEnvironment {
  return detectInstallEnvironment({
    maxTouchPoints: navigator.maxTouchPoints,
    platform: navigator.platform,
    userAgent: navigator.userAgent,
  });
}

type InstallEnvironmentKey =
  "ios" | "android" | "in-app" | "unsupported-mobile" | "unsupported";

function browserEnvironmentKey(): InstallEnvironmentKey {
  const environment = browserEnvironment();
  return (
    environment.instructionKind ??
    (environment.mobile ? "unsupported-mobile" : "unsupported")
  );
}

function environmentFromKey(key: InstallEnvironmentKey): InstallEnvironment {
  if (key === "unsupported") return unsupportedEnvironment;
  if (key === "unsupported-mobile") {
    return { mobile: true, supported: false };
  }
  return { instructionKind: key, mobile: true, supported: true };
}

function subscribeToBrowserSnapshot() {
  return () => undefined;
}

const unsupportedEnvironment: InstallEnvironment = {
  mobile: false,
  supported: false,
};

export type InstallExperienceInitialState = {
  environment: InstallEnvironment;
  firstLaunchComplete?: boolean;
  installed?: boolean;
  instructionsOpen?: boolean;
  promotionEligible?: boolean;
};

export function InstallExperienceProvider({
  children,
  initialState,
}: {
  children: React.ReactNode;
  initialState?: InstallExperienceInitialState;
}) {
  const environmentKey = React.useSyncExternalStore<InstallEnvironmentKey>(
    subscribeToBrowserSnapshot,
    browserEnvironmentKey,
    () => "unsupported",
  );
  const detectedStandalone = React.useSyncExternalStore(
    subscribeToBrowserSnapshot,
    isStandaloneDisplayMode,
    () => false,
  );
  const storedFirstLaunchComplete = React.useSyncExternalStore(
    subscribeToBrowserSnapshot,
    () => readFlag(installStorageKeys.firstLaunch),
    () => true,
  );
  const environment =
    initialState?.environment ?? environmentFromKey(environmentKey);
  const [appInstalled, setAppInstalled] = React.useState(
    initialState?.installed ?? false,
  );
  const [installPrompt, setInstallPrompt] =
    React.useState<BeforeInstallPromptEvent>();
  const [promotionEligible, setPromotionEligible] = React.useState(
    initialState?.promotionEligible ?? false,
  );
  const [instructionsOpen, setInstructionsOpen] = React.useState(
    initialState?.instructionsOpen ?? false,
  );
  const [firstLaunchAcknowledged, setFirstLaunchAcknowledged] =
    React.useState(false);
  const installed =
    initialState?.installed ?? (detectedStandalone || appInstalled);
  const firstLaunchComplete =
    (initialState?.firstLaunchComplete ?? storedFirstLaunchComplete) ||
    firstLaunchAcknowledged;

  React.useEffect(() => {
    function captureInstallPrompt(event: Event) {
      event.preventDefault();
      setInstallPrompt(event as BeforeInstallPromptEvent);
    }
    function markInstalled() {
      setAppInstalled(true);
      setPromotionEligible(false);
      setInstallPrompt(undefined);
    }
    window.addEventListener("beforeinstallprompt", captureInstallPrompt);
    window.addEventListener("appinstalled", markInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", captureInstallPrompt);
      window.removeEventListener("appinstalled", markInstalled);
    };
  }, []);

  const status = resolveInstallStatus({ environment, installed });
  const promotionVisible =
    promotionEligible && environment.supported && status !== "installed";

  const dismissPromotion = React.useCallback(() => {
    writeFlag(installStorageKeys.promotion);
    setPromotionEligible(false);
  }, []);

  const markPromotionShown = React.useCallback(() => {
    writeFlag(installStorageKeys.promotion);
  }, []);

  const recordCoreAction = React.useCallback(() => {
    if (readFlag(installStorageKeys.promotion)) return;
    setPromotionEligible(true);
  }, []);

  const completeFirstLaunch = React.useCallback(() => {
    writeFlag(installStorageKeys.firstLaunch);
    setFirstLaunchAcknowledged(true);
  }, []);

  const openInstallExperience = React.useCallback(async () => {
    writeFlag(installStorageKeys.promotion);
    setPromotionEligible(false);
    if (installPrompt) {
      await installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      if (choice.outcome === "accepted") setAppInstalled(true);
      setInstallPrompt(undefined);
      return;
    }
    setInstructionsOpen(true);
  }, [installPrompt]);

  const value = React.useMemo<InstallExperienceValue>(
    () => ({
      completeFirstLaunch,
      dismissPromotion,
      firstLaunchHintVisible: installed && !firstLaunchComplete,
      instructionKind: environment.instructionKind,
      instructionsOpen,
      markPromotionShown,
      openInstallExperience,
      promotionVisible,
      recordCoreAction,
      setInstructionsOpen,
      showInstallEntry:
        environment.mobile && environment.supported && status !== "installed",
      status,
    }),
    [
      completeFirstLaunch,
      dismissPromotion,
      environment,
      firstLaunchComplete,
      installed,
      instructionsOpen,
      markPromotionShown,
      openInstallExperience,
      promotionVisible,
      recordCoreAction,
      status,
    ],
  );

  return (
    <InstallExperienceContext.Provider value={value}>
      {children}
    </InstallExperienceContext.Provider>
  );
}

export function useInstallExperience() {
  const value = React.useContext(InstallExperienceContext);
  if (!value) {
    throw new Error(
      "useInstallExperience must be used within InstallExperienceProvider",
    );
  }
  return value;
}
