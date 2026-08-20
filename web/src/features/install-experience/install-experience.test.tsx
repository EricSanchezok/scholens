import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  InstallExperienceProvider,
  installStorageKeys,
  useInstallExperience,
} from "./install-experience";

const iosEnvironment = {
  instructionKind: "ios" as const,
  mobile: true,
  supported: true,
};

function Probe() {
  const experience = useInstallExperience();
  return (
    <>
      <output>{experience.status}</output>
      <output>{experience.promotionVisible ? "visible" : "hidden"}</output>
      <button onClick={experience.recordCoreAction}>Complete action</button>
      <button onClick={() => void experience.openInstallExperience()}>
        Install
      </button>
    </>
  );
}

describe("install experience", () => {
  beforeEach(() => localStorage.clear());

  it("waits for a core action before promoting installation", () => {
    render(
      <InstallExperienceProvider initialState={{ environment: iosEnvironment }}>
        <Probe />
      </InstallExperienceProvider>,
    );
    expect(screen.getByText("hidden")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Complete action" }));
    expect(screen.getByText("visible")).toBeInTheDocument();
  });

  it("does not repeat a promotion recorded by an earlier visit", () => {
    localStorage.setItem(installStorageKeys.promotion, "1");
    render(
      <InstallExperienceProvider initialState={{ environment: iosEnvironment }}>
        <Probe />
      </InstallExperienceProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Complete action" }));
    expect(screen.getByText("hidden")).toBeInTheDocument();
  });

  it("recognizes an installed first launch until sign-in completes", () => {
    function FirstLaunchProbe() {
      const experience = useInstallExperience();
      return (
        <button onClick={experience.completeFirstLaunch}>
          {experience.firstLaunchHintVisible ? "Sign in once" : "Complete"}
        </button>
      );
    }
    render(
      <InstallExperienceProvider
        initialState={{
          environment: iosEnvironment,
          firstLaunchComplete: false,
          installed: true,
        }}
      >
        <FirstLaunchProbe />
      </InstallExperienceProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Sign in once" }));
    expect(screen.getByRole("button", { name: "Complete" })).toBeVisible();
    expect(localStorage.getItem(installStorageKeys.firstLaunch)).toBe("1");
  });
});
