"use client";

import { LazyMotion, MotionConfig } from "motion/react";

import { useMotionPreference } from "./motion-provider";

const loadMotionFeatures = () =>
  import("./motion-features").then((module) => module.default);

export function MotionRuntimeProvider({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { preference, resolved, skipAnimations } = useMotionPreference();

  return (
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
  );
}
