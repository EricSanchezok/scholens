import { describe, expect, it } from "vitest";

import {
  detectInstallEnvironment,
  resolveInstallStatus,
} from "./install-environment";

const iosSafari =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1";
const androidChrome =
  "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/140.0.0.0 Mobile Safari/537.36";

describe("install environment", () => {
  it("offers manual Home Screen instructions in iOS Safari", () => {
    const environment = detectInstallEnvironment({
      maxTouchPoints: 5,
      platform: "iPhone",
      userAgent: iosSafari,
    });
    expect(environment).toEqual({
      instructionKind: "ios",
      mobile: true,
      supported: true,
    });
    expect(resolveInstallStatus({ environment, installed: false })).toBe(
      "manual-ios",
    );
  });

  it("offers the Chromium installation path on Android", () => {
    const environment = detectInstallEnvironment({
      maxTouchPoints: 5,
      platform: "Linux armv8l",
      userAgent: androidChrome,
    });
    expect(resolveInstallStatus({ environment, installed: false })).toBe(
      "installable-chromium",
    );
  });

  it("guides WeChat users to a system browser", () => {
    const environment = detectInstallEnvironment({
      maxTouchPoints: 5,
      platform: "Linux armv8l",
      userAgent: `${androidChrome} MicroMessenger/8.0`,
    });
    expect(environment).toMatchObject({
      instructionKind: "in-app",
      supported: true,
    });
    expect(resolveInstallStatus({ environment, installed: false })).toBe(
      "manual-in-app",
    );
  });

  it("hides installation after standalone launch", () => {
    const environment = detectInstallEnvironment({
      maxTouchPoints: 5,
      platform: "iPhone",
      userAgent: iosSafari,
    });
    expect(resolveInstallStatus({ environment, installed: true })).toBe(
      "installed",
    );
  });
});
