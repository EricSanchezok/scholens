"use client";

import { useIsPresent } from "motion/react";
import { div as MotionDiv } from "motion/react-m";
import * as React from "react";

import { useMotionPreference } from "./motion-provider";

export const MotionPresence = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<typeof MotionDiv>
>(({ inert, ...props }, ref) => {
  const isPresent = useIsPresent();
  const { ready, resolved } = useMotionPreference();
  const reduced = resolved === "reduced";

  return (
    <MotionDiv
      {...props}
      aria-hidden={isPresent ? props["aria-hidden"] : true}
      data-motion-runtime=""
      exit={reduced ? undefined : props.exit}
      initial={ready && !reduced ? props.initial : false}
      inert={isPresent ? inert : true}
      layout={reduced ? false : props.layout}
      ref={ref}
    />
  );
});
MotionPresence.displayName = "MotionPresence";
