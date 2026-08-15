import type { Transition, Variants } from "motion/react";

import {
  motionDurations,
  motionEasings,
  motionSprings,
} from "@/design-system/generated/motion-metadata";

const seconds = (milliseconds: number) => milliseconds / 1000;

export const motionTransitions = {
  feedback: {
    duration: seconds(motionDurations.feedback),
    ease: motionEasings.standard,
  },
  enter: {
    duration: seconds(motionDurations.standard),
    ease: motionEasings.enter,
  },
  exit: {
    duration: seconds(motionDurations.fast),
    ease: motionEasings.exit,
  },
  deliberate: {
    duration: seconds(motionDurations.deliberate),
    ease: motionEasings.enter,
  },
  layout: {
    type: "spring",
    ...motionSprings.layout,
  },
  gentle: {
    type: "spring",
    ...motionSprings.gentle,
  },
} satisfies Record<string, Transition>;

export const motionVariants = {
  swap: {
    initial: { opacity: 0, y: 4 },
    animate: { opacity: 1, y: 0, transition: motionTransitions.enter },
    exit: { opacity: 0, y: 2, transition: motionTransitions.exit },
  },
  listItem: {
    initial: { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0, transition: motionTransitions.enter },
    exit: { opacity: 0, y: 4, transition: motionTransitions.exit },
  },
  panel: {
    initial: { opacity: 0, x: 8 },
    animate: { opacity: 1, x: 0, transition: motionTransitions.enter },
    exit: { opacity: 0, x: 4, transition: motionTransitions.exit },
  },
  focal: {
    initial: { opacity: 0, y: 8 },
    animate: {
      opacity: 1,
      y: 0,
      transition: motionTransitions.deliberate,
    },
    exit: { opacity: 0, y: 4, transition: motionTransitions.exit },
  },
} satisfies Record<string, Variants>;

export const motionStagger = {
  interval: 0.024,
  maximumChildren: 6,
  maximumDelay: 0.144,
} as const;
