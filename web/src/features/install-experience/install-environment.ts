export type InstallExperienceStatus =
  | "unsupported"
  | "manual-ios"
  | "manual-in-app"
  | "installable-chromium"
  | "installed";

export type InstallInstructionKind = "ios" | "android" | "in-app";

export type InstallEnvironment = {
  instructionKind?: InstallInstructionKind;
  mobile: boolean;
  supported: boolean;
};

export function detectInstallEnvironment({
  maxTouchPoints,
  platform,
  userAgent,
}: {
  maxTouchPoints: number;
  platform: string;
  userAgent: string;
}): InstallEnvironment {
  const inApp = /MicroMessenger/i.test(userAgent);
  if (inApp) {
    return { instructionKind: "in-app", mobile: true, supported: true };
  }

  const ios =
    /iPad|iPhone|iPod/i.test(userAgent) ||
    (platform === "MacIntel" && maxTouchPoints > 1);
  const iosSafari =
    ios &&
    /Safari/i.test(userAgent) &&
    !/CriOS|FxiOS|EdgiOS|OPiOS/i.test(userAgent);
  if (iosSafari) {
    return { instructionKind: "ios", mobile: true, supported: true };
  }

  if (/Android/i.test(userAgent)) {
    return { instructionKind: "android", mobile: true, supported: true };
  }

  return { mobile: ios, supported: false };
}

export function resolveInstallStatus({
  environment,
  installed,
}: {
  environment: InstallEnvironment;
  installed: boolean;
}): InstallExperienceStatus {
  if (installed) return "installed";
  if (environment.instructionKind === "ios") return "manual-ios";
  if (environment.instructionKind === "in-app") return "manual-in-app";
  if (environment.instructionKind === "android") {
    return "installable-chromium";
  }
  return "unsupported";
}
