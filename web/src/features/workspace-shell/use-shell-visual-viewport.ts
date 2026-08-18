"use client";

import * as React from "react";

export type ShellVisualViewport = {
  height: number;
  offsetTop: number;
};

/**
 * Keep the fixed workspace shell aligned to the browser visual viewport on
 * phones. Layout-viewport fixed positioning can leave the bottom dock under
 * expanding mobile browser chrome after client-side tab switches; refresh often
 * collapses that chrome and temporarily hides the bug.
 */
export function readShellVisualViewport(
  visualViewport?: { height: number; offsetTop: number } | null,
  innerHeight = 0,
): ShellVisualViewport {
  if (!visualViewport) {
    return { height: innerHeight, offsetTop: 0 };
  }
  return {
    height: visualViewport.height,
    offsetTop: visualViewport.offsetTop,
  };
}

export function useShellVisualViewport(
  enabled: boolean,
): ShellVisualViewport | null {
  const [viewport, setViewport] = React.useState<ShellVisualViewport | null>(
    null,
  );

  React.useEffect(() => {
    if (!enabled) {
      return;
    }

    const visualViewport = window.visualViewport;

    function update() {
      setViewport(
        readShellVisualViewport(
          visualViewport
            ? {
                height: visualViewport.height,
                offsetTop: visualViewport.offsetTop,
              }
            : null,
          window.innerHeight,
        ),
      );
    }

    update();
    window.addEventListener("resize", update);
    visualViewport?.addEventListener("resize", update);
    visualViewport?.addEventListener("scroll", update);

    return () => {
      window.removeEventListener("resize", update);
      visualViewport?.removeEventListener("resize", update);
      visualViewport?.removeEventListener("scroll", update);
    };
  }, [enabled]);

  return enabled ? viewport : null;
}
