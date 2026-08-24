import { cva } from "class-variance-authority";

/** Shared focus-surface intents. Visual behavior lives in globals.css. */
export const focusSurfaceVariants = cva("focus-recipe", {
  variants: {
    intent: {
      neutral: "focus-recipe-neutral",
      primary: "focus-recipe-primary",
      danger: "focus-recipe-danger",
      status: "focus-recipe-status",
      selection: "focus-recipe-selection",
      inline: "focus-recipe-inline",
      scroll: "focus-recipe-scroll",
    },
  },
  defaultVariants: { intent: "neutral" },
});
