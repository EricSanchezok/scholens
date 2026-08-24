"use client";

import * as React from "react";

type FocusOrigin = "keyboard" | "pointer" | null;

let lastInteraction: Exclude<FocusOrigin, null> = "keyboard";
let listening = false;
let pointerResetTimer: number | undefined;

function listenForInputModality() {
  if (listening || typeof document === "undefined") return;
  listening = true;

  document.addEventListener(
    "keydown",
    () => {
      if (pointerResetTimer !== undefined) {
        window.clearTimeout(pointerResetTimer);
        pointerResetTimer = undefined;
      }
      lastInteraction = "keyboard";
    },
    true,
  );
  document.addEventListener(
    "pointerdown",
    () => {
      lastInteraction = "pointer";
      if (pointerResetTimer !== undefined) {
        window.clearTimeout(pointerResetTimer);
      }
      pointerResetTimer = window.setTimeout(() => {
        lastInteraction = "keyboard";
        pointerResetTimer = undefined;
      });
    },
    true,
  );
}

/** Installs modality tracking before a lazy text control can auto-focus. */
export function InputModalityListener() {
  React.useEffect(listenForInputModality, []);
  return null;
}

type FocusHandlers<T extends HTMLElement> = Pick<
  React.HTMLAttributes<T>,
  "onBlur" | "onFocus"
>;

export function useTextControlFocus<T extends HTMLElement>({
  onBlur,
  onFocus,
}: FocusHandlers<T> = {}) {
  const [focusOrigin, setFocusOrigin] = React.useState<FocusOrigin>(null);

  React.useEffect(listenForInputModality, []);

  return {
    focusOrigin,
    focusHandlers: {
      onBlur(event: React.FocusEvent<T>) {
        setFocusOrigin(null);
        onBlur?.(event);
      },
      onFocus(event: React.FocusEvent<T>) {
        setFocusOrigin(lastInteraction);
        onFocus?.(event);
      },
    },
  };
}
